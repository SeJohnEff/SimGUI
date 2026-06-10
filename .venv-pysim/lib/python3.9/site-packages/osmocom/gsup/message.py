#!/usr/bin/env python3

# Python implementation of Osmocom GSUP protocol
#
# (C) 2024 by Harald Welte <laforge@osmocom.org>
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

"""
This is an encoder/decoder implementation for the Osmocom GSUP
protocol, built upon the osmocom.tlv and osmocom.construct
infrastructure.
"""

from enum import IntEnum
from typing import Tuple, Union
from construct import Int8ub, Int32ub, Byte, Bytes, GreedyBytes, BitsInteger, GreedyString
from construct import this, Struct, BitStruct, Enum, GreedyRange, Default, Switch
from construct import Optional as COptional

from osmocom.tlv import TLV_IE, TLV_IE_Collection
from osmocom.construct import TonNpi, OsmoRatType
from osmocom.construct import PaddedBcdAdapter, DnsAdapter, Ipv4Adapter, Ipv6Adapter

class GSUP_TLV_IE(TLV_IE):
    """Class representing the TLV format as used in Osmocom GSUP. It's a simple
    '8-bit tag / 8-bit length / value' variant."""

    @classmethod
    def _parse_tag_raw(cls, do: bytes) -> Tuple[int, bytes]:
        return do[0], do[1:]

    @classmethod
    def _parse_len(cls, do: bytes) -> Tuple[int, bytes]:
        return do[0], do[1:]

    def _encode_tag(self) -> bytes:
        return bytes([self.tag])

    def _encode_len(self, val: bytes) -> bytes:
        return bytes([len(val)])


class tlv:
    """TLV definitions for the GSUP IEs, utilizing the osmocom.tlv code. Keep this in sync with
    https://gitea.osmocom.org/osmocom/libosmocore/src/branch/master/include/osmocom/gsm/gsup.h"""
    class auth:
        """Nested TLV IEs within the AuthTuple."""
        class RAND(GSUP_TLV_IE, tag=0x20):
            _construct = GreedyBytes

        class SRES(GSUP_TLV_IE, tag=0x21):
            _construct = GreedyBytes

        class Kc(GSUP_TLV_IE, tag=0x22):
            _construct = GreedyBytes

        class IK(GSUP_TLV_IE, tag=0x23):
            _construct = GreedyBytes

        class CK(GSUP_TLV_IE, tag=0x24):
            _construct = GreedyBytes

        class AUTN(GSUP_TLV_IE, tag=0x25):
            _construct = GreedyBytes

        class AUTS(GSUP_TLV_IE, tag=0x26):
            _construct = GreedyBytes

        class RES(GSUP_TLV_IE, tag=0x27):
            _construct = GreedyBytes

    class pdp:
        """Nested TLV IEs within the PdpInfo."""
        class PdpContextId(GSUP_TLV_IE, tag=0x10):
            _construct = Int8ub

        class PdpAddress(GSUP_TLV_IE, tag=0x11):
            _construct = Struct('hdr'/BitStruct('_spare'/Default(BitsInteger(4), 0xf),
                                                'pdp_type_org'/Enum(BitsInteger(4), ietf=1),
                                                'pdp_type_nr'/Enum(BitsInteger(8), ipv4=0x21, ipv6=0x57,
                                                                   ipv4v6=0x8d)),
                                'address'/COptional(Switch(this.hdr.pdp_type_nr,
                                                 {'ipv4': Ipv4Adapter(Bytes(4)),
                                                  'ipv6': Ipv6Adapter(Bytes(16)),
                                                  'ipv4v6': Struct('ipv4'/Ipv4Adapter(Bytes(4)),
                                                                   'ipv6'/Ipv6Adapter(Bytes(16)))})))


        class AccessPointName(GSUP_TLV_IE, tag=0x12):
            _construct = DnsAdapter(GreedyBytes)

        class Qos(GSUP_TLV_IE, tag=0x13):
            _construct = GreedyBytes

        class PdpChargingCharacteristics(GSUP_TLV_IE, tag=0x14):
            _construct = BitStruct('profile_index'/BitsInteger(4), 'behaviour'/BitsInteger(12))

    class IMSI(GSUP_TLV_IE, tag=0x01):
        _construct = PaddedBcdAdapter(GreedyBytes)

    class Cause(GSUP_TLV_IE, tag=0x02):
        _construct = Int8ub

    # osmocom/gsup/message.py:104:51: E0602: Undefined variable 'auth' (undefined-variable)
    # pylint: disable=undefined-variable
    class AuthTuple(GSUP_TLV_IE, tag=0x03, nested=[auth.RAND, auth.SRES, auth.Kc, auth.IK,
                                                   auth.CK, auth.AUTN, auth.RES]):
        pass

    class PdpInfoCompl(GSUP_TLV_IE, tag=0x04):
        _construct = None # emtpy

    class PdpInfo(GSUP_TLV_IE, tag=0x05, nested=[pdp.PdpContextId, pdp.PdpAddress, pdp.AccessPointName,
                                                 pdp.Qos, pdp.PdpChargingCharacteristics]):
        pass

    class CancelType(GSUP_TLV_IE, tag=0x06):
        _construct = Enum(Int8ub, update=0, withdraw=1)

    class FreezePTMSI(GSUP_TLV_IE, tag=0x07):
        _construct = None # empty

    class MSISDN(GSUP_TLV_IE, tag=0x08):
        _construct = Struct('bcd_len'/Byte, 'digits'/PaddedBcdAdapter(Bytes(this.bcd_len)))

    class HlrNumber(GSUP_TLV_IE, tag=0x09):
        _construct = Struct('ton_npi'/TonNpi, 'digits'/PaddedBcdAdapter(GreedyBytes))

    class MessageClass(GSUP_TLV_IE, tag=0x0a):
        _construct = Enum(Int8ub, subscriber_management=1, sms=2, ussd=3, inter_msc=4, ipsec_epdg=5)

    class PCO(GSUP_TLV_IE, tag=0x15):
        _construct = GreedyBytes # TODO: further decode

    class CnDomain(GSUP_TLV_IE, tag=0x28):
        _construct = Enum(Byte, ps=1, cs=2)

    class SupportedRatTypes(GSUP_TLV_IE, tag=0x29):
        _construct = OsmoRatType

    class CurrentRatType(GSUP_TLV_IE, tag=0x2a):
        _construct = GreedyRange(OsmoRatType)

    class SessionId(GSUP_TLV_IE, tag=0x30):
        _construct = Int32ub

    class SessionState(GSUP_TLV_IE, tag=0x31):
        _construct = Enum(Int8ub, undefined=0, begin=1, Continue=2, end=3)

    class SupplementaryServiceInfo(GSUP_TLV_IE, tag=0x35):
        _construct = GreedyBytes # TODO: further decode

    class SmRpMr(GSUP_TLV_IE, tag=0x40):
        _construct = Int8ub

    class SmRpDa(GSUP_TLV_IE, tag=0x41):
        _construct = Struct('ton_npi'/TonNpi, 'digits'/PaddedBcdAdapter(GreedyBytes))

    class SmRpOa(GSUP_TLV_IE, tag=0x42):
        _construct = Struct('ton_npi'/TonNpi, 'digits'/PaddedBcdAdapter(GreedyBytes))

    class SmRpUi(GSUP_TLV_IE, tag=0x43):
        _construct = GreedyBytes

    class SmRpCause(GSUP_TLV_IE, tag=0x44):
        _construct = Int8ub

    class SmRpMms(GSUP_TLV_IE, tag=0x45):
        _construct = None # empty

    class SmAlert(GSUP_TLV_IE, tag=0x46):
        _construct = Enum(Int8ub, ms_present=1, memory_available=2)

    class IMEI(GSUP_TLV_IE, tag=0x50):
        _construct = Struct('bcd_len'/Byte, 'digits'/PaddedBcdAdapter(Bytes(this.bcd_len)))

    class ImeiCheckResult(GSUP_TLV_IE, tag=0x51):
        _construct = Enum(Int8ub, ack=0, nack=1)

    class NumVectorsReq(GSUP_TLV_IE, tag=0x52):
        _construct = Int8ub

    class SourceName(GSUP_TLV_IE, tag=0x60):
        _construct = GreedyString('ascii')

    class DestinationName(GSUP_TLV_IE, tag=0x61):
        _construct = GreedyString('ascii')

    class AnApdu(GSUP_TLV_IE, tag=0x62):
        _construct = Struct('protocol'/Enum(Int8ub, bssap=1, ranap=2),
                            'data'/GreedyBytes)

    class CauseRr(GSUP_TLV_IE, tag=0x63):
        _construct = Int8ub

    class CauseBssap(GSUP_TLV_IE, tag=0x64):
        _construct = Int8ub

    class CauseSm(GSUP_TLV_IE, tag=0x65):
        _construct = Int8ub

    class IeCollection(TLV_IE_Collection, nested=[IMSI, Cause, AuthTuple, PdpInfoCompl, PdpInfo, CancelType,
                                                  FreezePTMSI, MSISDN, HlrNumber, MessageClass, PCO, CnDomain,
                                                  SupportedRatTypes, CurrentRatType, SessionId, SessionState,
                                                  SupplementaryServiceInfo, SmRpMr, SmRpOa, SmRpUi, SmRpCause,
                                                  SmRpMms, SmAlert, IMEI, ImeiCheckResult, NumVectorsReq,
                                                  SourceName, DestinationName, AnApdu, CauseRr, CauseBssap,
                                                  CauseSm, auth.RAND, auth.AUTS]):
        pass

class MsgType(IntEnum):
    """GSUP protocol message type. Keep this in sync with
    https://gitea.osmocom.org/osmocom/libosmocore/src/branch/master/include/osmocom/gsm/gsup.h"""

    UPDATE_LOCATION_REQUEST = 0x04
    UPDATE_LOCATION_ERROR   = 0x05
    UPDATE_LOCATION_RESULT  = 0x06

    SEND_AUTH_INFO_REQUEST  = 0x08
    SEND_AUTH_INFO_ERROR    = 0x09
    SEND_AUTH_INFO_RESULT   = 0x0a

    AUTH_FAIL_REPORT        = 0x0b

    PURGE_MS_REQUEST        = 0x0c
    PURGE_MS_ERROR          = 0x0d
    PURGE_MS_RESULT         = 0x0e

    INSERT_DATA_REQUEST     = 0x10
    INSERT_DATA_ERROR       = 0x11
    INSERT_DATA_RESULT      = 0x12

    DELETE_DATA_REQUEST     = 0x14
    DELETE_DATA_ERROR       = 0x15
    DELETE_DATA_RESULT      = 0x16

    LOCATION_CANCEL_REQUEST = 0x1c
    LOCATION_CANCEL_ERROR   = 0x1d
    LOCATION_CANCEL_RESULT  = 0x1e

    PROC_SS_REQUEST         = 0x20
    PROC_SS_ERROR           = 0x21
    PROC_SS_RESULT          = 0x22

    MO_FORWARD_SM_REQUEST   = 0x24
    MO_FORWARD_SM_ERROR     = 0x25
    MO_FORWARD_SM_RESULT    = 0x26

    MT_FORWARD_SM_REQUEST   = 0x28
    MT_FORWARD_SM_ERROR     = 0x29
    MT_FORWARD_SM_RESULT    = 0x2a

    READY_FOR_SM_REQUEST    = 0x2c
    READY_FOR_SM_ERROR      = 0x2d
    READY_FOR_SM_RESULT     = 0x2e

    CHECK_IMEI_REQUEST      = 0x30
    CHECK_IMEI_ERROR        = 0x31
    CHECK_IMEI_RESULT       = 0x32

    E_PREPARE_HANDOVER_REQUEST      = 0x34
    E_PREPARE_HANDOVER_ERROR        = 0x35
    E_PREPARE_HANDOVER_RESULT       = 0x36

    E_PREPARE_SUBSEQUENT_HANDOVER_REQUEST   = 0x38
    E_PREPARE_SUBSEQUENT_HANDOVER_ERROR     = 0x39
    E_PREPARE_SUBSEQUENT_HANDOVER_RESULT    = 0x3a

    E_SEND_END_SIGNAL_REQUEST       = 0x3c
    E_SEND_END_SIGNAL_ERROR         = 0x3d
    E_SEND_END_SIGNAL_RESULT        = 0x3e

    E_PROCESS_ACCESS_SIGNALLING_REQUEST    = 0x40
    E_FORWARD_ACCESS_SIGNALLING_REQUEST    = 0x44

    E_CLOSE                 = 0x47
    E_ABORT                 = 0x4b

    ROUTING_ERROR           = 0x4e

    EPDG_TUNNEL_REQUEST     = 0x50
    EPDG_TUNNEL_ERROR       = 0x51
    EPDG_TUNNEL_RESULT      = 0x52

class GsupMessage:
    """Represents a single message within the GSUP protocol."""

    def __init__(self, msg_type: Union[MsgType, int]):
        if isinstance(msg_type, MsgType):
            self.msg_type = msg_type
        else:
            self.msg_type = MsgType(msg_type)
        self.ies = tlv.IeCollection()

    def __str__(self) -> str:
        return '%s(%s, %s)' % (self.__class__.__name__, self.msg_type, str(self.ies))

    def __repr__(self) -> str:
        return '%s(%s, %s)' % (self.__class__.__name__, self.msg_type, str(self.ies))

    @classmethod
    def from_bytes(cls, encoded: bytes) -> 'GsupMessage':
        """Create a GsupMessage instance from the decode of the given bytes."""
        msg = GsupMessage(encoded[0])
        msg.ies.from_bytes(encoded[1:])
        return msg

    @classmethod
    def from_dict(cls, decoded: dict) -> 'GsupMessage':
        """Create a GsupMessage instance from the decoded dict."""
        msg = GsupMessage(MsgType[decoded['msg_type']])
        msg.ies.from_dict(decoded['ies'])
        return msg

    def to_bytes(self):
        """Encode a GsupMessage instance into bytes."""
        return bytes([self.msg_type.value]) + self.ies.to_bytes()

    def to_dict(self):
        """Encode a GsupMessage instance into a json-serializable dict."""
        return {'msg_type': self.msg_type.name,
                'ies': self.ies.to_dict()}
