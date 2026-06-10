"""TLV parser/encoder library supporting various formats."""

# (C) 2021 by Harald Welte <laforge@osmocom.org>
# All Rights Reserved
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import inspect
import abc
import re
from typing import List, Tuple, Optional

import osmocom

#########################################################################
# poor man's COMPREHENSION-TLV decoder.
#########################################################################

def comprehensiontlv_parse_tag_raw(binary: bytes) -> Tuple[int, bytes]:
    """Parse a single Tag according to ETSI TS 101 220 Section 7.1.1"""
    if binary[0] in [0x00, 0x80, 0xff]:
        raise ValueError("Found illegal value 0x%02x in %s" %
                         (binary[0], binary))
    if binary[0] == 0x7f:
        # three-byte tag
        tag = binary[0] << 16 | binary[1] << 8 | binary[2]
        return (tag, binary[3:])
    elif binary[0] == 0xff:
        return None, binary
    else:
        # single byte tag
        tag = binary[0]
        return (tag, binary[1:])

def comprehensiontlv_parse_tag(binary: bytes) -> Tuple[dict, bytes]:
    """Parse a single Tag according to ETSI TS 101 220 Section 7.1.1"""
    if binary[0] in [0x00, 0x80, 0xff]:
        raise ValueError("Found illegal value 0x%02x in %s" %
                         (binary[0], binary))
    if binary[0] == 0x7f:
        # three-byte tag
        tag = (binary[1] & 0x7f) << 8
        tag |= binary[2]
        compr = bool(binary[1] & 0x80)
        return ({'comprehension': compr, 'tag': tag}, binary[3:])
    else:
        # single byte tag
        tag = binary[0] & 0x7f
        compr = bool(binary[0] & 0x80)
        return ({'comprehension': compr, 'tag': tag}, binary[1:])

def comprehensiontlv_encode_tag(tag) -> bytes:
    """Encode a single Tag according to ETSI TS 101 220 Section 7.1.1"""
    # permit caller to specify tag also as integer value
    if isinstance(tag, int):
        compr = bool(tag < 0xff and tag & 0x80)
        tag = {'tag': tag, 'comprehension': compr}
    compr = tag.get('comprehension', False)
    if tag['tag'] in [0x00, 0x80, 0xff] or tag['tag'] > 0xff:
        # 3-byte format
        byte3 = tag['tag'] & 0xff
        byte2 = (tag['tag'] >> 8) & 0x7f
        if compr:
            byte2 |= 0x80
        return b'\x7f' + byte2.to_bytes(1, 'big') + byte3.to_bytes(1, 'big')
    else:
        # 1-byte format
        ret = tag['tag']
        if compr:
            ret |= 0x80
        return ret.to_bytes(1, 'big')

# length value coding is equal to BER-TLV

def comprehensiontlv_parse_one(binary: bytes) -> Tuple[dict, int, bytes, bytes]:
    """Parse a single TLV IE at the start of the given binary data.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (tag:dict, len:int, remainder:bytes)
    """
    (tagdict, remainder) = comprehensiontlv_parse_tag(binary)
    (length, remainder) = bertlv_parse_len(remainder)
    value = remainder[:length]
    remainder = remainder[length:]
    return (tagdict, length, value, remainder)


#########################################################################
# poor man's BER-TLV decoder. To be a more sophisticated OO library later
#########################################################################

def bertlv_parse_tag_raw(binary: bytes) -> Tuple[int, bytes]:
    """Get a single raw Tag from start of input according to ITU-T X.690 8.1.2
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
    Tuple of (tag:int, remainder:bytes)
    """
    # check for FF padding at the end, as customary in SIM card files
    if binary[0] == 0xff and len(binary) == 1 or binary[0] == 0xff and binary[1] == 0xff:
        return None, binary
    tag = binary[0] & 0x1f
    if tag <= 30:
        return binary[0], binary[1:]
    else:  # multi-byte tag
        tag = binary[0]
        i = 1
        last = False
        while not last:
            last = not bool(binary[i] & 0x80)
            tag <<= 8
            tag |= binary[i]
            i += 1
        return tag, binary[i:]

def bertlv_parse_tag(binary: bytes) -> Tuple[dict, bytes]:
    """Parse a single Tag value according to ITU-T X.690 8.1.2
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of ({class:int, constructed:bool, tag:int}, remainder:bytes)
    """
    cls = binary[0] >> 6
    constructed = bool(binary[0] & 0x20)
    tag = binary[0] & 0x1f
    if tag <= 30:
        return ({'class': cls, 'constructed': constructed, 'tag': tag}, binary[1:])
    else:  # multi-byte tag
        tag = 0
        i = 1
        last = False
        while not last:
            last = not bool(binary[i] & 0x80)
            tag <<= 7
            tag |= binary[i] & 0x7f
            i += 1
        return ({'class': cls, 'constructed': constructed, 'tag': tag}, binary[i:])

def bertlv_encode_tag(t) -> bytes:
    """Encode a single Tag value according to ITU-T X.690 8.1.2
    """
    def get_top7_bits(inp: int) -> Tuple[int, int]:
        """Get top 7 bits of integer. Returns those 7 bits as integer and the remaining LSBs."""
        remain_bits = inp.bit_length()
        if remain_bits >= 7:
            bitcnt = 7
        else:
            bitcnt = remain_bits
        outp = inp >> (remain_bits - bitcnt)
        remainder = inp & ~ (inp << (remain_bits - bitcnt))
        return outp, remainder

    def count_int_bytes(inp: int) -> int:
        """count the number of bytes require to represent the given integer."""
        i = 1
        inp = inp >> 8
        while inp:
            i += 1
            inp = inp >> 8
        return i

    if isinstance(t, int):
        # first convert to a dict representation
        tag_size = count_int_bytes(t)
        t, _remainder = bertlv_parse_tag(t.to_bytes(tag_size, 'big'))
    tag = t['tag']
    constructed = t['constructed']
    cls = t['class']
    if tag <= 30:
        t = tag & 0x1f
        if constructed:
            t |= 0x20
        t |= (cls & 3) << 6
        return bytes([t])
    else:  # multi-byte tag
        t = 0x1f
        if constructed:
            t |= 0x20
        t |= (cls & 3) << 6
        tag_bytes = bytes([t])
        remain = tag
        while True:
            t, remain = get_top7_bits(remain)
            if remain:
                t |= 0x80
            tag_bytes += bytes([t])
            if not remain:
                break
        return tag_bytes

def bertlv_parse_len(binary: bytes) -> Tuple[int, bytes]:
    """Parse a single Length value according to ITU-T X.690 8.1.3;
    only the definite form is supported here.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (length, remainder)
    """
    if binary[0] < 0x80:
        return (binary[0], binary[1:])
    else:
        num_len_oct = binary[0] & 0x7f
        length = 0
        if len(binary) < num_len_oct + 1:
            return (0, b'')
        for i in range(1, 1+num_len_oct):
            length <<= 8
            length |= binary[i]
        return (length, binary[1+num_len_oct:])

def bertlv_encode_len(length: int) -> bytes:
    """Encode a single Length value according to ITU-T X.690 8.1.3;
    only the definite form is supported here.
    Args:
            length : length value to be encoded
    Returns:
            binary output data of BER-TLV length field
    """
    if length < 0x80:
        return length.to_bytes(1, 'big')
    elif length <= 0xff:
        return b'\x81' + length.to_bytes(1, 'big')
    elif length <= 0xffff:
        return b'\x82' + length.to_bytes(2, 'big')
    elif length <= 0xffffff:
        return b'\x83' + length.to_bytes(3, 'big')
    elif length <= 0xffffffff:
        return b'\x84' + length.to_bytes(4, 'big')
    else:
        raise ValueError("Length > 32bits not supported")

def bertlv_parse_one(binary: bytes) -> Tuple[dict, int, bytes, bytes]:
    """Parse a single TLV IE at the start of the given binary data.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (tag:dict, len:int, remainder:bytes)
    """
    (tagdict, remainder) = bertlv_parse_tag(binary)
    (length, remainder) = bertlv_parse_len(remainder)
    value = remainder[:length]
    remainder = remainder[length:]
    return (tagdict, length, value, remainder)

def bertlv_parse_one_rawtag(binary: bytes) -> Tuple[int, int, bytes, bytes]:
    """Parse a single TLV IE at the start of the given binary data; return tag as raw integer.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (tag:int, len:int, remainder:bytes)
    """
    (tag, remainder) = bertlv_parse_tag_raw(binary)
    (length, remainder) = bertlv_parse_len(remainder)
    value = remainder[:length]
    remainder = remainder[length:]
    return (tag, length, value, remainder)

def bertlv_return_one_rawtlv(binary: bytes) -> Tuple[int, int, bytes, bytes]:
    """Return one single [encoded] TLV IE at the start of the given binary data.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (tag:int, len:int, tlv:bytes, remainder:bytes)
    """
    (tag, remainder) = bertlv_parse_tag_raw(binary)
    (length, remainder) = bertlv_parse_len(remainder)
    tl_length = len(binary) - len(remainder)
    value = binary[:tl_length] + remainder[:length]
    remainder = remainder[length:]
    return (tag, length, value, remainder)

#########################################################################
# poor man's DGI decoder.
#########################################################################

def dgi_parse_tag_raw(binary: bytes) -> Tuple[int, bytes]:
    # In absence of any clear spec guidance we assume it's always 16 bit
    return int.from_bytes(binary[:2], 'big'), binary[2:]

def dgi_encode_tag(t: int) -> bytes:
    return t.to_bytes(2, 'big')

def dgi_encode_len(length: int) -> bytes:
    """Encode a single Length value according to GlobalPlatform Systems Scripting Language
    Specification v1.1.0 Annex B.
    Args:
            length : length value to be encoded
    Returns:
            binary output data of encoded length field
    """
    if length < 255:
        return length.to_bytes(1, 'big')
    elif length <= 0xffff:
        return b'\xff' + length.to_bytes(2, 'big')
    else:
        raise ValueError("Length > 32bits not supported")

def dgi_parse_len(binary: bytes) -> Tuple[int, bytes]:
    """Parse a single Length value according to  GlobalPlatform Systems Scripting Language
    Specification v1.1.0 Annex B.
    Args:
            binary : binary input data of BER-TLV length field
    Returns:
            Tuple of (length, remainder)
    """
    if binary[0] == 255:
        assert len(binary) >= 3
        return ((binary[1] << 8) | binary[2]), binary[3:]
    else:
        return binary[0], binary[1:]


#########################################################################
# rich-man's object oriented TLV decoders/encoders
#########################################################################

def camel_to_snake(name):
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

class TlvMeta(abc.ABCMeta):
    """Metaclass which we use to set some class variables at the time of defining a subclass.
    This allows us to create subclasses for each TLV/IE type, where the class represents fixed
    parameters like the tag/type and instances of it represent the actual TLV data."""
    def __new__(mcs, name, bases, namespace, **kwargs):
        #print("TlvMeta_new_(mcs=%s, name=%s, bases=%s, namespace=%s, kwargs=%s)" % (mcs, name, bases, namespace, kwargs))
        x = super().__new__(mcs, name, bases, namespace)
        # this becomes a _class_ variable, not an instance variable
        x.tag = namespace.get('tag', kwargs.get('tag', None))
        x.desc = namespace.get('desc', kwargs.get('desc', None))
        nested = namespace.get('nested', kwargs.get('nested', None))
        if nested is None or inspect.isclass(nested) and issubclass(nested, TLV_IE_Collection):
            # caller has specified TLV_IE_Collection sub-class, we can directly reference it
            x.nested_collection_cls = nested
        else:
            # caller passed list of other TLV classes that might possibly appear within us,
            # build a dynamically-created TLV_IE_Collection sub-class and reference it
            name = 'auto_collection_%s' % (name)
            cls = type(name, (TLV_IE_Collection,), {'nested': nested})
            x.nested_collection_cls = cls
        return x


class TlvCollectionMeta(abc.ABCMeta):
    """Metaclass which we use to set some class variables at the time of defining a subclass.
    This allows us to create subclasses for each Collection type, where the class represents fixed
    parameters like the nested IE classes and instances of it represent the actual TLV data."""
    def __new__(mcs, name, bases, namespace, **kwargs):
        #print("TlvCollectionMeta_new_(mcs=%s, name=%s, bases=%s, namespace=%s, kwargs=%s)" % (mcs, name, bases, namespace, kwargs))
        x = super().__new__(mcs, name, bases, namespace)
        # this becomes a _class_ variable, not an instance variable
        x.possible_nested = namespace.get('nested', kwargs.get('nested', None))
        return x


class Transcodable(abc.ABC):
    _construct = None
    """Base class for something that can be encoded + encoded.  Decoding and Encoding happens either
     * via a 'construct' object stored in a derived class' _construct variable, or
     * via a 'construct' object stored in an instance _construct variable, or
     * via a derived class' _{to,from}_bytes() methods."""

    def __init__(self):
        self.encoded = None
        self.decoded = None
        self._construct = None

    def to_bytes(self, context: dict = {}) -> bytes:
        """Convert from internal representation to binary bytes.  Store the binary result
        in the internal state and return it."""
        if self.decoded is None:
            do = b''
        elif self._construct:
            do = osmocom.construct.build_construct(self._construct, self.decoded, context)
        elif self.__class__._construct:
            do = osmocom.construct.build_construct(self.__class__._construct, self.decoded, context)
        else:
            do = self._to_bytes()
        self.encoded = do
        return do

    # not an abstractmethod, as it is only required if no _construct exists
    def _to_bytes(self):
        raise NotImplementedError('%s._to_bytes' % type(self).__name__)

    def from_bytes(self, do: bytes, context: dict = {}):
        """Convert from binary bytes to internal representation. Store the decoded result
        in the internal state and return it."""
        self.encoded = do
        if self.encoded == b'':
            self.decoded = None
        elif self._construct:
            self.decoded = osmocom.construct.parse_construct(self._construct, do, context=context)
        elif self.__class__._construct:
            self.decoded = osmocom.construct.parse_construct(self.__class__._construct, do, context=context)
        else:
            self.decoded = self._from_bytes(do)
        return self.decoded

    # not an abstractmethod, as it is only required if no _construct exists
    def _from_bytes(self, do: bytes):
        raise NotImplementedError('%s._from_bytes' % type(self).__name__)


class IE(Transcodable, metaclass=TlvMeta):
    # we specify the metaclass so any downstream subclasses will automatically use it
    """Base class for various Information Elements. We understand the notion of a hierarchy
    of IEs on top of the Transcodable class."""
    # this is overridden by the TlvMeta metaclass, if it is used to create subclasses
    nested_collection_cls = None
    tag = None

    def __init__(self, **kwargs):
        super().__init__()
        self.nested_collection = None
        if self.nested_collection_cls:
            # pylint: disable=not-callable
            self.nested_collection = self.nested_collection_cls()
        # if we are a constructed IE, [ordered] list of actual child-IE instances
        self.children = kwargs.get('children', [])
        self.decoded = kwargs.get('decoded', None)

    def __repr__(self):
        """Return a string representing the [nested] IE data (for print)."""
        if len(self.children):
            member_strs = [repr(x) for x in self.children]
            return '%s(%s)' % (type(self).__name__, ','.join(member_strs))
        else:
            return '%s(%s)' % (type(self).__name__, self.decoded)

    def to_val_dict(self):
        """Return a JSON-serializable dict representing just the [nested] value portion of the IE
        data.  This does not include any indication of the type of 'self', so the resulting dict alone
        will be insufficient ot recreate an object from it without additional type information."""
        if len(self.children):
            return [x.to_dict() for x in self.children]
        else:
            return self.decoded

    def from_val_dict(self, decoded):
        """Set the IE internal decoded representation to data from the argument.
        If this is a nested IE, the child IE instance list is re-created.

        This method is symmetrical to to_val_dict() aboe, i.e. there is no outer dict
        containig the snake-reformatted type name of 'self'."""
        if self.nested_collection:
            self.children = self.nested_collection.from_dict(decoded)
        else:
            self.children = []
            self.decoded = decoded

    def to_dict(self):
        """Return a JSON-serializable dict representing the [nested] IE data.  The returned
        data contains an outer dict with the snake-reformatted type of 'self' and is hence
        sufficient to re-create an object from it."""
        return {camel_to_snake(type(self).__name__): self.to_val_dict()}

    def from_dict(self, decoded: dict):
        """Set the IE internal decoded representation to data from the argument.
        If this is a nested IE, the child IE instance list is re-created.

        This method is symmetrical to to_dict() above, i.e. the outer dict must contain just a single
        key-value pair, where the key is the snake-reformatted type name of 'self'"""
        expected_key_name = camel_to_snake(type(self).__name__)
        if not expected_key_name in decoded:
            raise ValueError("Dict %s doesn't contain expected key %s" % (decoded, expected_key_name))
        self.from_val_dict(decoded[expected_key_name])

    def is_constructed(self):
        """Is this IE constructed by further nested IEs?"""
        return bool(len(self.children) > 0)

    @abc.abstractmethod
    def to_ie(self, context: dict = {}) -> bytes:
        """Convert the internal representation to entire IE including IE header."""

    def to_bytes(self, context: dict = {}) -> bytes:
        """Convert the internal representation *of the value part* to binary bytes."""
        if self.is_constructed():
            # concatenate the encoded IE of all children to form the value part
            out = b''
            for c in self.children:
                out += c.to_ie(context=context)
            return out
        else:
            return super().to_bytes(context=context)

    def from_bytes(self, do: bytes, context: dict = {}):
        """Parse *the value part* from binary bytes to internal representation."""
        if self.nested_collection:
            self.children = self.nested_collection.from_bytes(do, context=context)
        else:
            self.children = []
            return super().from_bytes(do, context=context)

    def child_by_name(self, name: str) -> Optional['IE']:
        """Return a child IE instance of given snake-case/json type name. This only works in case
        there is no more than one child IE of the given type."""
        children = list(filter(lambda c: camel_to_snake(type(c).__name__) == name, self.children))
        if len(children) > 1:
            raise KeyError('There are multiple children of class %s' % name)
        elif len(children) == 1:
            return children[0]

    def child_by_type(self, cls) -> Optional['IE']:
        """Return a child IE instance of given type (class). This only works in case
        there is no more than one child IE of the given type."""
        children = list(filter(lambda c: isinstance(c, cls), self.children))
        if len(children) > 1:
            raise KeyError('There are multiple children of class %s' % cls)
        elif len(children) == 1:
            return children[0]


class TLV_IE(IE):
    """Abstract base class for various TLV type Information Elements."""

    def _compute_tag(self) -> int:
        """Compute the tag (sometimes the tag encodes part of the value)."""
        return self.tag

    @classmethod
    @abc.abstractmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        """Obtain the raw TAG at the start of the bytes provided by the user."""

    @classmethod
    @abc.abstractmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        """Obtain the length encoded at the start of the bytes provided by the user."""

    @abc.abstractmethod
    def _encode_tag(self) -> bytes:
        """Encode the tag part. Must be provided by derived (TLV format specific) class."""

    @abc.abstractmethod
    def _encode_len(self, val: bytes) -> bytes:
        """Encode the length part assuming a certain binary value. Must be provided by
        derived (TLV format specific) class."""

    def to_ie(self, context: dict = {}):
        return self.to_tlv(context=context)

    def to_tlv(self, context: dict = {}):
        """Convert the internal representation to binary TLV bytes."""
        val = self.to_bytes(context=context)
        return self._encode_tag() + self._encode_len(val) + val

    def is_tag_compatible(self, rawtag) -> bool:
        """Is the given rawtag compatible with this class?"""
        return rawtag == self._compute_tag()

    def from_tlv(self, do: bytes, context: dict = {}):
        if len(do) == 0:
            return {}, b''
        (rawtag, remainder) = self.__class__._parse_tag_raw(do)
        if rawtag:
            if not self.is_tag_compatible(rawtag):
                raise ValueError("%s: Encountered tag %s doesn't match our supported tag %s" %
                                 (self, rawtag, self.tag))
            (length, remainder) = self.__class__._parse_len(remainder)
            value = remainder[:length]
            remainder = remainder[length:]
        else:
            value = do
            remainder = b''
        dec = self.from_bytes(value, context=context)
        return dec, remainder


class COMPACT_TLV_IE(TLV_IE):
    """TLV_IE formatted as COMPACT-TLV described in ISO 7816"""

    @classmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        return do[0] >> 4, do

    @classmethod
    def _decode_tag(cls, do: bytes) -> Tuple[dict, bytes]:
        rawtag, remainder = cls._parse_tag_raw(do)
        return {'tag': rawtag}, remainder

    @classmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        return do[0] & 0xf, do[1:]

    def _encode_tag(self) -> bytes:
        """Not needed as we override the to_tlv() method to encode tag+length into one byte."""
        raise NotImplementedError

    def _encode_len(self):
        """Not needed as we override the to_tlv() method to encode tag+length into one byte."""
        raise NotImplementedError

    def to_tlv(self, context: dict = {}):
        val = self.to_bytes(context=context)
        return bytes([(self.tag << 4) | (len(val) & 0xF)]) + val


class BER_TLV_IE(TLV_IE):
    """TLV_IE formatted as ASN.1 BER described in ITU-T X.690 8.1.2."""

    @classmethod
    def _decode_tag(cls, do: bytes) -> Tuple[dict, bytes]:
        return bertlv_parse_tag(do)

    @classmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        return bertlv_parse_tag_raw(do)

    @classmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        return bertlv_parse_len(do)

    def _encode_tag(self) -> bytes:
        return bertlv_encode_tag(self._compute_tag())

    def _encode_len(self, val: bytes) -> bytes:
        return bertlv_encode_len(len(val))


class ComprTlvMeta(TlvMeta):
    def __new__(mcs, name, bases, namespace, **kwargs):
        x = super().__new__(mcs, name, bases, namespace, **kwargs)
        if x.tag:
            # we currently assume that the tag values always have the comprehension bit set;
            # let's fix it up if a derived class has forgotten about that
            if x.tag > 0xff and x.tag & 0x8000 == 0:
                print("Fixing up COMPR_TLV_IE class %s: tag=0x%x has no comprehension bit" % (name, x.tag))
                x.tag = x.tag | 0x8000
            elif x.tag & 0x80 == 0:
                print("Fixing up COMPR_TLV_IE class %s: tag=0x%x has no comprehension bit" % (name, x.tag))
                x.tag = x.tag | 0x80
        return x

class COMPR_TLV_IE(TLV_IE, metaclass=ComprTlvMeta):
    """TLV_IE formated as COMPREHENSION-TLV as described in ETSI TS 101 220."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.comprehension = False

    @classmethod
    def _decode_tag(cls, do: bytes) -> Tuple[dict, bytes]:
        return comprehensiontlv_parse_tag(do)

    @classmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        return comprehensiontlv_parse_tag_raw(do)

    @classmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        return bertlv_parse_len(do)

    def is_tag_compatible(self, rawtag: int) -> bool:
        """Override is_tag_compatible as we need to mask out the
        comprehension bit when doing compares."""
        ctag = self._compute_tag()
        if ctag > 0xff:
            return ctag & 0x7fff == rawtag & 0x7fff
        else:
            return ctag & 0x7f == rawtag & 0x7f

    def _encode_tag(self) -> bytes:
        return comprehensiontlv_encode_tag(self._compute_tag())

    def _encode_len(self, val: bytes) -> bytes:
        return bertlv_encode_len(len(val))


class DGI_TLV_IE(TLV_IE):
    """TLV_IE formated as  GlobalPlatform Systems Scripting Language Specification v1.1.0 Annex B."""

    @classmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        return dgi_parse_tag_raw(do)

    @classmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        return dgi_parse_len(do)

    def _encode_tag(self) -> bytes:
        return dgi_encode_tag(self._compute_tag())

    def _encode_len(self, val: bytes) -> bytes:
        return dgi_encode_len(len(val))


class TLV_IE_Collection(metaclass=TlvCollectionMeta):
    # we specify the metaclass so any downstream subclasses will automatically use it
    """A TLV_IE_Collection consists of multiple TLV_IE classes identified by their tags.
    A given encoded DO may contain any of them in any order, and may contain multiple instances
    of each DO."""
    # this is overridden by the TlvCollectionMeta metaclass, if it is used to create subclasses
    possible_nested = []

    def __init__(self, desc=None, **kwargs):
        self.desc = desc
        #print("possible_nested: ", self.possible_nested)
        self.members = kwargs.get('nested', self.possible_nested)
        self.members_by_tag = {}
        self.members_by_name = {}
        self.members_by_tag = {m.tag: m for m in self.members}
        self.members_by_name = {camel_to_snake(m.__name__): m for m in self.members}
        # if we are a constructed IE, [ordered] list of actual child-IE instances
        self.children = kwargs.get('children', [])
        self.encoded = None

    def __str__(self):
        member_strs = [str(x) for x in self.members]
        return '%s(%s)' % (type(self).__name__, ','.join(member_strs))

    def __repr__(self):
        member_strs = [repr(x) for x in self.members]
        return '%s(%s)' % (self.__class__, ','.join(member_strs))

    def __add__(self, other):
        """Extending TLV_IE_Collections with other TLV_IE_Collections or TLV_IEs."""
        if isinstance(other, TLV_IE_Collection):
            # adding one collection to another
            members = self.members + other.members
            return TLV_IE_Collection(self.desc, nested=members)
        elif inspect.isclass(other) and issubclass(other, TLV_IE):
            # adding a member to a collection
            return TLV_IE_Collection(self.desc, nested=self.members + [other])
        else:
            raise TypeError

    def from_bytes(self, binary: bytes, context: dict = {}) -> List[TLV_IE]:
        """Create a list of TLV_IEs from the collection based on binary input data.
        Args:
            binary : binary bytes of encoded data
        Returns:
            list of instances of TLV_IE sub-classes containing parsed data
        """
        self.encoded = binary
        # list of instances of TLV_IE collection member classes appearing in the data
        res = []
        remainder = binary
        first = next(iter(self.members_by_tag.values()))
        # iterate until no binary trailer is left
        while len(remainder):
            context['siblings'] = res
            # obtain the tag at the start of the remainder
            tag, _r = first._parse_tag_raw(remainder)
            if tag is None:
                break
            if issubclass(first, COMPR_TLV_IE):
                tag = tag | 0x80 # HACK: always assume comprehension
            if tag in self.members_by_tag:
                cls = self.members_by_tag[tag]
                # create an instance and parse accordingly
                inst = cls()
                _dec, remainder = inst.from_tlv(remainder, context=context)
                res.append(inst)
            else:
                # unknown tag; create the related class on-the-fly using the same base class
                name = 'unknown_%s_%X' % (first.__base__.__name__, tag)
                cls = type(name, (first.__base__,), {'tag': tag, 'possible_nested': [],
                                                     'nested_collection_cls': None})
                cls._from_bytes = lambda s, a: {'raw': a.hex()}
                cls._to_bytes = lambda s: bytes.fromhex(s.decoded['raw'])
                # create an instance and parse accordingly
                inst = cls()
                _dec, remainder = inst.from_tlv(remainder, context=context)
                res.append(inst)
        self.children = res
        return res

    def from_dict(self, decoded: List[dict]) -> List[TLV_IE]:
        """Create a list of TLV_IE instances from the collection based on an array
        of dicts, where they key indicates the name of the TLV_IE subclass to use."""
        # list of instances of TLV_IE collection member classes appearing in the data
        res = []
        # iterate over members of the list passed into "decoded"
        for i in decoded:
            # iterate over all the keys (typically one!) within the current list item dict
            for k in i.keys():
                # check if we have a member identified by the dict key
                if k in self.members_by_name:
                    # resolve the class for that name; create an instance of it
                    cls = self.members_by_name[k]
                    inst = cls()
                    inst.from_dict({k: i[k]})
                    res.append(inst)
                else:
                    raise ValueError('%s: Unknown TLV Class %s in %s; expected %s' %
                                     (self, k, decoded, self.members_by_name.keys()))
        self.children = res
        return res

    def to_dict(self):
        # we intentionally return not a dict, but a list of dicts.  We could prefix by
        # self.__class__.__name__, but that is usually some meaningless auto-generated  collection name.
        return [x.to_dict() for x in self.children]

    def to_bytes(self, context: dict = {}):
        out = b''
        context['siblings'] = self.children
        for c in self.children:
            out += c.to_tlv(context=context)
        return out

    def from_tlv(self, do, context: dict = {}):
        return self.from_bytes(do, context=context)

    def to_tlv(self, context: dict = {}):
        return self.to_bytes(context=context)


def flatten_dict_lists(inp):
    """hierarchically flatten each list-of-dicts into a single dict. This is useful to
       make the output of hierarchical TLV decoder structures flatter and more easy to read."""
    def are_all_elements_dict(l):
        for e in l:
            if not isinstance(e, dict):
                return False
        return True

    def are_elements_unique(lod):
        set_of_keys = {list(x.keys())[0] for x in lod}
        return len(lod) == len(set_of_keys)

    if isinstance(inp, list):
        if are_all_elements_dict(inp) and are_elements_unique(inp):
            # flatten into one shared dict
            newdict = {}
            for e in inp:
                key = list(e.keys())[0]
                newdict[key] = e[key]
            inp = newdict
            # process result as any native dict
            return {k:flatten_dict_lists(v) for k,v in inp.items()}
        else:
            return [flatten_dict_lists(x) for x in inp]
    elif isinstance(inp, dict):
        return {k:flatten_dict_lists(v) for k,v in inp.items()}
    else:
        return inp
