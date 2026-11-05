# Checkpoint encryption

Conversation checkpoints (graph state, tool results, pending writes, approval
interrupts) are written to the checkpoint SQLite database. They can be
encrypted at rest. It is off by default; an application turns it on.

## How it works

- Checkpoint blobs are sealed with AES-256-GCM (the `cryptography` package, the
  same primitive the vault uses).
- The key is derived from the vault KEK with HKDF-SHA256 (salt: the app's
  configured vault salt; info: `checkpoints|v<version>`). No new secret is
  needed: whatever unlocks the vault (OS keyring, `<PREFIX>_VAULT_KEK_FILE`, or
  `<PREFIX>_VAULT_PASSPHRASE`) unlocks checkpoints.
- Each blob carries a small header with a key id such as `v1-3f9a…`. The header
  is authenticated, so it cannot be altered without the read failing.
- The serializer plugs into LangGraph's `EncryptedSerializer`; stored rows get
  a type like `msgpack+aes256gcm`.

Once encryption is on there is no plaintext fallback: a missing vault key stops
the saver from opening, and a wrong key or tampered row raises an error naming
the key id.

## Settings

| Setting (env) | Default | Meaning |
| --- | --- | --- |
| `checkpoint_encryption` (`YARVELLE_CORE_CHECKPOINT_ENCRYPTION`) | `false` | Encrypt new checkpoints. |
| `checkpoint_plaintext_reads` (`YARVELLE_CORE_CHECKPOINT_PLAINTEXT_READS`) | `true` | Keep reading old plaintext rows. Turn off after migrating. |
| `checkpoint_key_version` (`YARVELLE_CORE_CHECKPOINT_KEY_VERSION`) | `1` | Active key version. Older versions stay readable. |

## Turning it on for an existing install

1. Set `checkpoint_encryption=true`. New checkpoints are encrypted; old
   plaintext threads keep working.
2. Stop the app and run the migration:

   ```bash
   yarvelle-core checkpoints status
   yarvelle-core checkpoints encrypt --dry-run
   yarvelle-core checkpoints encrypt
   ```

   `encrypt` writes a backup copy next to the database
   (`<db>.bak-<timestamp>`, skip with `--no-backup`), rewrites every plaintext
   row in one transaction, then vacuums the file so replaced plaintext does not
   stay in free pages. Running it again changes nothing.
3. Set `checkpoint_plaintext_reads=false`.
4. Delete the backup once you have checked the app. It still holds plaintext.

`--db PATH` points at a specific database; `--json` prints a machine-readable
report.

## Rotating the key

Raise `checkpoint_key_version` (for example to `2`). New rows use the v2 key and
v1 rows stay readable. `yarvelle-core checkpoints encrypt` re-encrypts the old
rows to the active version.

Changing the vault KEK itself is different: rows written under the old KEK can
only be read with it, so run `checkpoints decrypt` with the old KEK first, then
switch the KEK and run `checkpoints encrypt`.

## Turning it off again

Stop the app, run `yarvelle-core checkpoints decrypt` (with the vault key
available), then set `checkpoint_encryption=false`. With encryption off, an
encrypted row produces a clear error rather than garbage.

## What is not covered

- Checkpoint metadata (thread id, step, source, run and profile ids) is stored
  by LangGraph as plain JSON next to the blob and is not encrypted.
- Audit bodies (`audit_store_bodies`) and long-term memory stores are separate
  and not affected.
- Turn task records store only status, timing and SHA-256 hashes of the hand-off
  input and output, never the text.
