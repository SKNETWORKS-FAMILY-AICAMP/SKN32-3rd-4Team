# Manuals

Operational how-to documents. Written in **English** so they stay copy-pasteable
regardless of console encoding — a Korean command pasted into `cmd.exe` on a
CP949 console gets mangled, and we lost time to exactly that.

| Document | What it covers |
|---|---|
| [ssh-gpu-access.md](ssh-gpu-access.md) | Passwordless SSH to the GPU box (`10.20.20.1`) |

---

## ★ The one rule these manuals exist for

**Every command block says which machine it runs on.**

We burned four rounds on the SSH setup because commands were pasted on the wrong
machine. The public key ended up in `C:\ProgramData\ssh\administrators_authorized_keys`
on the **laptop** instead of the **GPU box**, and the symptom looked identical to a
permission problem.

So each block below is prefixed with one of:

```
### RUN ON: LAPTOP   (the machine you develop on)
### RUN ON: GPU BOX  (10.20.20.1 — physically at it, or via Remote Desktop)
```

If a block does not say where it runs, it is a bug in the manual. Fix the manual.
