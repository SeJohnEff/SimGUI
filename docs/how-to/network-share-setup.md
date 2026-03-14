# How to: Configure an SMB network share

SimGUI can read card data files and write programming artifacts to an SMB (Samba / Windows) network share. This centralises card data in a team environment and provides an automatic audit trail of every programmed card.

**Prerequisites:**

- SimGUI installed and working
- An SMB server accessible on your local network (Windows file share, Samba on Linux, NAS appliance, etc.)
- Credentials for a share with read/write access
- `cifs-utils` installed (included by the SimGUI installer)

---

## What the network share is used for

| Use | Directory on share |
|---|---|
| Card data CSV and EML files | Any location on the share (you browse to them) |
| Auto-artifact CSVs (one per programmed card) | `auto-artifact/` — created automatically |
| `standards.json` canonical values | Root of the share (e.g. `//server/share/standards.json`) |

The `auto-artifact/` directory is created on first write. No manual setup of subdirectories is required.

---

## Step 1: Verify share access from the command line

Before configuring SimGUI, confirm the share is reachable:

```bash
smbclient -L //SERVER_NAME -U username
```

List the contents of a specific share:

```bash
smbclient //SERVER_NAME/SHARENAME -U username -c "ls"
```

If this fails, troubleshoot network connectivity and credentials before proceeding.

---

## Step 2: Create a mount point

```bash
sudo mkdir -p /mnt/simgui-share
```

Choose any path; `/mnt/simgui-share` is a suggestion.

---

## Step 3: Mount the share

```bash
sudo mount -t cifs //SERVER_NAME/SHARENAME /mnt/simgui-share \
  -o username=YOUR_USERNAME,password=YOUR_PASSWORD,uid=$(id -u),gid=$(id -g)
```

Replace:
- `SERVER_NAME` — hostname or IP of the SMB server
- `SHARENAME` — the share name
- `YOUR_USERNAME` / `YOUR_PASSWORD` — your credentials

> **Security note:** Avoid embedding passwords in command history. Use a credentials file instead:
>
> ```bash
> # Create a credentials file
> echo "username=YOUR_USERNAME" | sudo tee /etc/simgui-smb-creds
> echo "password=YOUR_PASSWORD" | sudo tee -a /etc/simgui-smb-creds
> sudo chmod 600 /etc/simgui-smb-creds
>
> # Mount using the credentials file
> sudo mount -t cifs //SERVER_NAME/SHARENAME /mnt/simgui-share \
>   -o credentials=/etc/simgui-smb-creds,uid=$(id -u),gid=$(id -g)
> ```

---

## Step 4: Make the mount persistent (optional but recommended)

Add to `/etc/fstab` so the share mounts on boot:

```
//SERVER_NAME/SHARENAME  /mnt/simgui-share  cifs  credentials=/etc/simgui-smb-creds,uid=1000,gid=1000,_netdev  0  0
```

Replace `uid=1000,gid=1000` with your actual user and group IDs (`id -u` and `id -g`).

The `_netdev` option tells the system to wait for network availability before mounting.

---

## Step 5: Configure SimGUI to use the share

Open SimGUI and go to **Settings → Network Storage** (or the network storage dialog):

1. Click **Add Share**.
2. Select the mount point (`/mnt/simgui-share`).
3. Give it a label (e.g. "Lab NAS").
4. Click **OK**.

<!-- screenshot: network-storage-dialog-configured -->

SimGUI immediately checks for `standards.json` at the root of the mount point and loads canonical SPN and LI values if found. The status line shows "Loaded standards from /mnt/simgui-share/standards.json: N SPN, M LI values".

---

## Step 6: Test artifact writing

Program a card (or run a simulator session) and check that a file appears in `auto-artifact/`:

```bash
ls /mnt/simgui-share/auto-artifact/
```

Expected output:

```
8988211812345678901_20260314_103045.csv
```

The filename format is `{ICCID}_{YYYYMMDD_HHMMSS}.csv`.

---

## Network auto-discovery

SimGUI can discover SMB servers on your local network automatically via mDNS (Avahi) and NetBIOS. In the Network Storage dialog, click **Discover** to scan. Discovered servers appear in a list; click one to populate the server field.

Auto-discovery requires `avahi-utils` to be installed (included with the SimGUI installer).

---

## Multiple shares

SimGUI supports multiple simultaneously mounted shares. Standards are merged from all mounted shares (values de-duplicated, preserving case from the file). Auto-artifacts are written to **all** connected shares in parallel — useful when mirroring data to a backup NAS.

---

## Unmounting

```bash
sudo umount /mnt/simgui-share
```

When a share is unmounted, SimGUI clears the cached standards values and stops writing artifacts to that path. No data loss occurs for previously saved artifacts.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `mount error(13): Permission denied` | Wrong credentials or SMB ACL | Verify username/password, check server ACLs |
| `mount error(115): Operation now in progress` | Network unreachable | Check network; use `_netdev` in fstab |
| Standards not loaded | `standards.json` missing or malformed | See [Create and maintain standards.json](standards-file.md) |
| Artifacts not saved | Share unmounted or permissions wrong | Check mount, verify write permission with `touch` test |
| `smbclient: command not found` | `smbclient` not installed | `sudo apt install smbclient` |

For SMB-specific issues see [Troubleshooting](troubleshooting.md).
