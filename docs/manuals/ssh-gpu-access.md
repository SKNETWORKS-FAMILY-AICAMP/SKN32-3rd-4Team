# Passwordless SSH to the GPU box

Target: `Yeon@10.20.20.1` (Windows, OpenSSH server, account is a **local administrator**)

Goal: the laptop can run commands on the GPU box **without typing a password**, so
long benchmark jobs can be launched and monitored automatically.

---

## ★ Read this first — why it kept failing

Three separate traps, all hit in one afternoon (2026-08-02):

| # | What went wrong | Symptom |
|---|---|---|
| 1 | `ssh-copy-id` was used on Windows PowerShell | `'ssh-copy-id' is not recognized` — it only ships with Git Bash |
| 2 | A Linux-style command was sent to a Windows server | `The system cannot find the path specified.` — the remote shell is `cmd.exe`, which has no `mkdir -p` or `umask` |
| 3 | **The key was installed on the wrong machine** | Command reported success, but SSH still asked for a password |

Trap 3 is the expensive one. The prompt looked the same on both machines
(`PS C:\Users\playdata2>`), so a command meant for the GPU box ran on the laptop.

**That is why every block below states its machine.**

---

## ★ The Windows administrator trap

Windows OpenSSH does **not** read `~/.ssh/authorized_keys` for accounts in the
local Administrators group. `sshd_config` on this box contains:

```
Match Group administrators
       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
```

So the key must go into `C:\ProgramData\ssh\administrators_authorized_keys`.

That directory needs an **elevated** token to write. An SSH session opened as an
administrator still runs with a UAC-filtered (non-elevated) token, so writing the
file *over SSH* silently fails. It has to be done at the machine, elevated.

---

## Step 1 — Get the public key

### RUN ON: LAPTOP

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Expected output (one line):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKMQPGIZdPDJRYl+Q+VgmB3q0R72IPhXlrInRMcJZldO zweing@gmail.com
```

If the file does not exist, create the key pair first:

```powershell
ssh-keygen -t ed25519 -C "your-email@example.com"
```

Press Enter at every prompt to accept the defaults and use no passphrase.
(A passphrase would defeat the purpose — unattended jobs cannot type it.)

---

## Step 2 — Install the key **on the GPU box**

### RUN ON: GPU BOX (10.20.20.1)

Go to the machine physically, or connect with Remote Desktop.
Open PowerShell **as Administrator** (right-click → *Run as administrator*).

> **How to confirm you are elevated and on the right machine:**
> ```powershell
> hostname; whoami; (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole('Administrators')
> ```
> The hostname must be the GPU box, and the last line must print `True`.
> If it prints `False`, the window is not elevated — close it and reopen as administrator.

Then paste the key from Step 1:

```powershell
$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKMQPGIZdPDJRYl+Q+VgmB3q0R72IPhXlrInRMcJZldO zweing@gmail.com'
Add-Content C:\ProgramData\ssh\administrators_authorized_keys -Value $key -Encoding ascii
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant SYSTEM:F /grant *S-1-5-32-544:F
```

**The `icacls` line is not optional.** Windows OpenSSH silently ignores this file
if anyone other than `SYSTEM` and `Administrators` has access to it — no error is
logged on the client, you just keep getting a password prompt.

`*S-1-5-32-544` is the well-known SID for the local Administrators group. The SID
is used instead of the group name because the name is localized (`Administrators`
on English Windows, and other strings elsewhere).

---

## Step 3 — Verify

### RUN ON: LAPTOP

```powershell
ssh -o BatchMode=yes Yeon@10.20.20.1 "hostname"
```

`BatchMode=yes` disables the password prompt, so this **only** succeeds if the key
works. Do not verify without it — a successful password login proves nothing.

- Prints the hostname → done.
- `Permission denied (publickey,...)` → the key is not being accepted. Go to Troubleshooting.

---

## Troubleshooting

### RUN ON: LAPTOP — is the key even being offered?

```powershell
ssh -v -o BatchMode=yes Yeon@10.20.20.1 "hostname"
```

Look for:

```
debug1: Offering public key: .../id_ed25519 ED25519 SHA256:...
debug1: Authentications that can continue: publickey,password,keyboard-interactive
```

If the key **is** offered and still rejected, the problem is on the server —
the file, or its permissions.

### RUN ON: GPU BOX — inspect the server side

```powershell
type C:\ProgramData\ssh\administrators_authorized_keys
icacls C:\ProgramData\ssh\administrators_authorized_keys
findstr /i administrators C:\ProgramData\ssh\sshd_config
```

| What you see | What it means |
|---|---|
| `The system cannot find the file specified` | The key was never written. The earlier command ran on the wrong machine, or without elevation |
| Key present, but ACL lists `Users` / `Authenticated Users` / the account name | Permissions are too open — rerun the `icacls` line from Step 2 |
| Key present, ACL correct, still failing | Check the key is on **one line** and not wrapped or truncated |

### RUN ON: GPU BOX — read the server log

```powershell
Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 20 | Format-List TimeCreated, Message
```

This states the actual reason, e.g. *"Authentication refused: bad ownership or
modes for file"*.

---

## What this unblocks

Once passwordless SSH works, the embedding-model comparison runs on the GPU
instead of laptop CPU (roughly 9 items/sec → far faster, and models too large for
the laptop's 15 GB free disk are downloaded, measured, then deleted one at a time).

### RUN ON: LAPTOP — build the evaluation set (needs the policy corpus, which lives here)

```powershell
python -m scripts.eval.build_retrieval_set
```

### RUN ON: LAPTOP — copy the evaluation set and scripts to the GPU box

```powershell
scp data\eval\embed_bench.json Yeon@10.20.20.1:C:/work/insurance/data/eval/
```

> **Note on the data:** `embed_bench.json` contains ~2,000 excerpts of insurance
> policy text. That text is copyrighted and is not committed to git. Copying it to
> an internal lab machine is fine; do not copy it anywhere outside the team.

### RUN ON: GPU BOX — run the benchmark

```powershell
bash scripts/eval/remote_bench.sh
```

Each candidate is downloaded, measured, and purged from the HuggingFace cache
before the next one starts. A failed model does not stop the run — it is counted
and reported at the end, so "we measured everything" is never claimed falsely.

---

## Related

- [`scripts/eval/remote_bench.sh`](../../scripts/eval/remote_bench.sh) — the runner
- [`scripts/eval/bench_embedders.py`](../../scripts/eval/bench_embedders.py) — measures one model
- [Embedding model candidates](../reports/2026-08-02_1800_임베딩모델_후보_20선_코덱스합의.md) — what is being compared and why
