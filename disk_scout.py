#!/usr/bin/env python3
"""
Disk Scout for Debian and derivatives
Read-only disk audit with optional, separately confirmed cleanup actions.

Default: audit only. No files are deleted, no services are stopped, and no
containers/VMs are changed during the audit.

Examples:
  python3 disk_scout.py
  python3 disk_scout.py --min-gb 2
  python3 disk_scout.py --report ~/disk-scout-report.txt
  python3 disk_scout.py --cleanup-apt-cache
  python3 disk_scout.py --cleanup-user-cache

Notes:
- Run as your normal user, NOT with sudo. Some system paths may be inaccessible.
- VM disks, containers, volumes, AI models, repositories and personal files are
  reported only; this script never deletes them.
- Every report list that has a measurable size is sorted largest-to-smallest.
  Lists based on counts (such as inode density) are sorted highest-to-lowest.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
__version__ = "2.1.0"
HOME = Path.home()
GIB = 1024 ** 3
MIB = 1024 ** 2

# These are only inspected/reported, never removed.
KNOWN_STORAGE_PATHS = [
    HOME / "VirtualBox VMs",
    HOME / "VMs",
    HOME / "virtual-machines",
    HOME / ".local/share/containers",
    HOME / ".local/share/libvirt/images",
    HOME / ".var/app",
    HOME / ".cache/huggingface",
    HOME / ".ollama/models",
    HOME / ".cache/torch",
    HOME / ".cache/pip",
    HOME / ".cache",
    Path("/var/lib/docker"),
    Path("/var/lib/containers"),
    Path("/var/lib/libvirt/images"),
    Path("/var/cache/apt/archives"),
    Path("/var/log"),
]

MODEL_EXTENSIONS = {
    ".gguf", ".ggml", ".safetensors", ".ckpt", ".pt", ".pth",
    ".onnx", ".bin", ".model"
}
VM_EXTENSIONS = {
    ".qcow2", ".qcow", ".vdi", ".vmdk", ".vhd", ".vhdx", ".ova", ".ovf"
}
CONTAINER_MARKERS = {
    "overlay2", "containers", "volumes", "containerd", "docker"
}
SKIP_DIRS = {
    ".git", "proc", "sys", "dev", "run", "node_modules",
    ".venv", "venv", "__pycache__"
}


def fmt_size(n):
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def run_command(args, timeout=30):
    try:
        p = subprocess.run(
            args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Comando non trovato: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout dopo {timeout} secondi"
    except OSError as exc:
        return 1, "", str(exc)


def disk_overview():
    section("1. SPAZIO DISCO E MOUNT")
    code, out, err = run_command(["df", "-hT", "-x", "tmpfs", "-x", "devtmpfs"])
    print(out or err or "Impossibile leggere df.")
    print("\nFilesystem con inode potenzialmente esauriti:")
    code, out, err = run_command(["df", "-ih", "-x", "tmpfs", "-x", "devtmpfs"])
    print(out or err or "Impossibile leggere df -i.")


def du_summary(path, depth=2):
    """Read-only disk usage summary, staying on the same filesystem."""
    if not path.exists():
        return
    print(f"\n[{path}]")
    code, out, err = run_command(
        ["du", "-x", "-h", f"--max-depth={depth}", str(path)],
        timeout=180
    )
    if out:
        lines = out.splitlines()
        # Largest entries first, with root summary retained when possible.
        entries = []
        for line in lines:
            parts = line.split("\t", 1)
            if len(parts) == 2:
                entries.append((parts[0], parts[1]))
            else:
                entries.append(("", line))
        entries.sort(key=lambda item: (-size_key(item[0]), item[1].casefold()))
        for size, name in entries[:25]:
            print(f"  {size:>8}  {name}")
        if len(entries) > 25:
            print(f"  ... altre {len(entries) - 25} voci omesse")
    else:
        print("  Non leggibile o vuoto.")
        if err:
            print(" ", err.splitlines()[0])


def size_key(value):
    """Approximate sort for human-readable du sizes."""
    try:
        value = value.strip()
        # du may honor an Italian locale and print decimal commas (e.g. 4,1G).
        if value[-1].isalpha():
            number = float(value[:-1].replace(",", "."))
            unit = value[-1].upper()
            factor = {"B": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5}.get(unit, 0)
        else:
            number = float(value.replace(",", "."))
            factor = 0
        return number * (1024 ** factor)
    except (ValueError, IndexError):
        return 0


def storage_audit():
    section("2. DIRECTORY CHE SPESSO OCCUPANO MOLTO SPAZIO")
    seen = set()
    for path in KNOWN_STORAGE_PATHS:
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        du_summary(path, depth=2)


def scan_large_and_special_files(roots, min_bytes, max_results=120):
    section(f"3. FILE GRANDI E FILE VM / MODELLI AI (soglia {fmt_size(min_bytes)})")
    matches = []
    special = []
    visited = 0

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for current, dirs, files in os.walk(root, followlinks=False, onerror=lambda _e: None):
            # Avoid virtual filesystems and very noisy build/dependency trees.
            dirs[:] = [
                d for d in dirs
                if d not in SKIP_DIRS and not (Path(current) / d).is_symlink()
            ]
            for filename in files:
                p = Path(current) / filename
                try:
                    if p.is_symlink():
                        continue
                    st = p.stat()
                    if not p.is_file():
                        continue
                    visited += 1
                    ext = p.suffix.lower()
                    lower_parts = {part.lower() for part in p.parts}
                    record = (st.st_size, str(p), ext)
                    if st.st_size >= min_bytes:
                        matches.append(record)
                    if ext in MODEL_EXTENSIONS or ext in VM_EXTENSIONS:
                        special.append(record)
                except (OSError, PermissionError):
                    continue

    # Primary key: allocated logical file size, descending; path breaks ties.
    matches.sort(key=lambda item: (-item[0], item[1].casefold()))
    special.sort(key=lambda item: (-item[0], item[1].casefold()))

    print(f"File esaminati: {visited}")
    print("\nFile più grandi:")
    if not matches:
        print("  Nessun file sopra la soglia nei percorsi leggibili.")
    for size, path, ext in matches[:max_results]:
        print(f"  {fmt_size(size):>10}  {path}")

    print("\nPossibili immagini VM / modelli AI (solo segnalazione):")
    if not special:
        print("  Nessun file riconosciuto per estensione.")
    for size, path, ext in special[:max_results]:
        category = "VM" if ext in VM_EXTENSIONS else "AI"
        print(f"  [{category}] {fmt_size(size):>10}  {path}")
    if len(special) > max_results:
        print(f"  ... altre {len(special) - max_results} voci omesse")



def inode_filesystems():
    """Return mounted local filesystems and inode statistics."""
    section("4. ANALISI INODE — STATO DEI FILESYSTEM")
    code, out, err = run_command(
        ["df", "-i", "-P", "-x", "tmpfs", "-x", "devtmpfs"], timeout=45
    )
    if code != 0 or not out:
        print(err or "Impossibile ottenere le statistiche inode.")
        return []
    print(out)
    mounts = []
    lines = out.splitlines()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 6:
            continue
        filesystem, inodes, used, available, percent, mountpoint = fields[:6]
        try:
            total_n = int(inodes)
            used_n = int(used)
            avail_n = int(available)
        except ValueError:
            continue
        if total_n <= 0:
            continue
        pct = used_n / total_n * 100
        level = "CRITICO" if pct >= 97 else "ALTO" if pct >= 90 else "ATTENZIONE" if pct >= 75 else "OK"
        print(f"  [{level}] {mountpoint}: {pct:.1f}% — {used_n:,}/{total_n:,} inode, {avail_n:,} disponibili")
        mounts.append((mountpoint, filesystem))
    return mounts


def inode_directory_audit(roots, top_n=30):
    """
    Estimate directory-entry density without changing the filesystem.
    Counts regular files, symlinks and directories as entries. Hard links may
    appear more than once, so these are diagnostic counts, not exact inode
    ownership per directory.
    """
    section("5. INODE INTELLIGENCE — DIRECTORY AD ALTA DENSITÀ")
    print("Scansione in sola lettura. Conteggi = voci filesystem osservate;")
    print("hard link e mount annidati possono impedire un'attribuzione esatta.")
    totals = {}
    errors = 0
    scanned_dirs = 0
    scanned_entries = 0

    for root in roots:
        try:
            if not root.is_dir():
                continue
            root_stat = root.stat()
            root_dev = root_stat.st_dev
        except OSError:
            errors += 1
            continue

        # Each directory accumulates its own entries; values are then rolled
        # up to ancestors, yielding subtree density estimates.
        own = {}
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                if current.stat().st_dev != root_dev:
                    continue
                scanned_dirs += 1
                count = 0
                child_dirs = []
                with os.scandir(current) as iterator:
                    for entry in iterator:
                        try:
                            if entry.is_symlink():
                                count += 1
                                scanned_entries += 1
                            elif entry.is_dir(follow_symlinks=False):
                                count += 1
                                scanned_entries += 1
                                child_dirs.append(Path(entry.path))
                            else:
                                count += 1
                                scanned_entries += 1
                        except OSError:
                            errors += 1
                own[str(current)] = count
                stack.extend(child_dirs)
            except OSError:
                errors += 1

        # Bottom-up roll-up using path depth; this is an estimate of entries
        # below each directory, not a claim that every entry owns a unique inode.
        for dirname in sorted(own, key=lambda x: x.count(os.sep), reverse=True):
            parent = str(Path(dirname).parent)
            if parent in own:
                own[parent] += own[dirname]

        for dirname, count in own.items():
            totals[dirname] = max(totals.get(dirname, 0), count)

    print(f"Directory esaminate: {scanned_dirs:,}")
    print(f"Voci incontrate: {scanned_entries:,}")
    print(f"Errori/percorsi non accessibili: {errors:,}")
    print("\nDirectory con più voci nel sottoalbero (conteggio decrescente):")
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold()))
    if not ranked:
        print("  Nessun risultato (permessi, filesystem o percorsi non disponibili).")
    for dirname, count in ranked[:top_n]:
        print(f"  {count:>12,}  {dirname}")

    print("\nNota: i conteggi sono indicativi. Per una diagnosi puntuale,")
    print("confrontare le directory con il mount point e i valori di df -i.")

def container_audit():
    section("6. DOCKER / PODMAN (COMANDI DI SOLA LETTURA)")
    for command in (["docker", "system", "df", "-v"],
                    ["podman", "system", "df", "-v"]):
        code, out, err = run_command(command, timeout=45)
        print(f"\n$ {' '.join(command)}")
        if code == 0 and out:
            print(out)
        elif code == 127:
            print("  Comando non installato o non disponibile nel PATH.")
        else:
            print("  Non disponibile (servizio spento, permessi o errore).")
            if err:
                print(" ", err.splitlines()[0])

    print("\nIMPORTANTE: non usare prune alla cieca: immagini, container e volumi")
    print("possono contenere ambienti di lavoro o dati non facilmente ricostruibili.")


def vm_audit():
    section("7. VIRTUAL MACHINE")
    commands = [
        ["virsh", "list", "--all"],
        ["VBoxManage", "list", "vms"],
        ["qm", "list"],
    ]
    for command in commands:
        code, out, err = run_command(command, timeout=20)
        print(f"\n$ {' '.join(command)}")
        if code == 0 and out:
            print(out)
        elif code == 127:
            print("  Comando non installato.")
        else:
            print("  Non disponibile o senza permessi.")
            if err:
                print(" ", err.splitlines()[0])
    print("\nLe immagini disco sono soltanto individuate; nessuna VM viene modificata.")


def ai_audit():
    section("8. STRUMENTI / CACHE AI")
    for command in (["ollama", "list"],):
        code, out, err = run_command(command, timeout=30)
        print(f"\n$ {' '.join(command)}")
        if code == 0:
            print(out or "(nessun modello elencato)")
        elif code == 127:
            print("  Ollama non installato o non disponibile nel PATH.")
        else:
            print("  Non disponibile.")
            if err:
                print(" ", err.splitlines()[0])

    print("\nPercorsi controllati includono cache Hugging Face, Ollama e PyTorch.")
    print("La scansione per estensione non rileva necessariamente ogni formato modello.")


def cleanup_apt_cache():
    section("PULIZIA APT: OPERAZIONE ESPLICITA")
    print("Comando previsto: sudo apt-get clean")
    print("Rimuove archivi .deb scaricati dalla cache APT, non i pacchetti installati.")
    answer = input("Vuoi eseguire questo comando? Digita PULISCI per confermare: ")
    if answer != "PULISCI":
        print("Annullato.")
        return
    code, out, err = run_command(["sudo", "apt-get", "clean"], timeout=180)
    print(out or ("Operazione completata." if code == 0 else err))
    if code != 0:
        print(f"Comando terminato con codice {code}.")


def cleanup_user_cache():
    section("PULIZIA CACHE UTENTE: OPERAZIONE ESPLICITA")
    cache = HOME / ".cache"
    print(f"Percorso candidato: {cache}")
    print("Questa operazione elimina i contenuti della cache utente; alcune app")
    print("potrebbero dover rigenerare dati o scaricare nuovamente contenuti.")
    print("Non elimina documenti, repository, VM, container o modelli fuori da ~/.cache.")
    answer = input("Vuoi procedere? Digita PULISCI per confermare: ")
    if answer != "PULISCI":
        print("Annullato.")
        return
    if not cache.is_dir() or cache.is_symlink():
        print("Percorso non valido o collegamento simbolico: operazione bloccata.")
        return

    deleted_bytes = 0
    errors = 0
    # Delete contents only, never the ~/.cache directory itself.
    for child in cache.iterdir():
        try:
            if child.is_symlink():
                child.unlink()
            elif child.is_file():
                deleted_bytes += child.stat().st_size
                child.unlink()
            elif child.is_dir():
                for base, dirs, files in os.walk(child, followlinks=False):
                    dirs[:] = [
                        d for d in dirs if not (Path(base) / d).is_symlink()
                    ]
                    for name in files:
                        p = Path(base) / name
                        try:
                            if not p.is_symlink():
                                deleted_bytes += p.stat().st_size
                        except OSError:
                            pass
                shutil.rmtree(child)
        except OSError as exc:
            errors += 1
            print(f"Non eliminato {child}: {exc}")
    print(f"Dimensione teorica rimossa: {fmt_size(deleted_bytes)}")
    print(f"Voci non rimosse per errori/permessi: {errors}")


def main():
    parser = argparse.ArgumentParser(
        description="Audit prudente dello spazio disco per Debian e distribuzioni derivate."
    )
    parser.add_argument(
        "--min-gb", type=float, default=1.0,
        help="Soglia per mostrare file grandi in GB (default: 1)."
    )
    parser.add_argument(
        "--report", type=str,
        help="Salva l'output in un file di report (es. ~/disk-scout.txt)."
    )
    parser.add_argument(
        "--inode-top", type=int, default=30,
        help="Numero di directory da mostrare nella classifica inode (default: 30)."
    )
    parser.add_argument(
        "--skip-inode-scan", action="store_true",
        help="Salta la scansione ricorsiva delle directory per gli inode."
    )
    parser.add_argument(
        "--cleanup-apt-cache", action="store_true",
        help="Dopo l'audit, propone la pulizia della cache APT con conferma."
    )
    parser.add_argument(
        "--cleanup-user-cache", action="store_true",
        help="Dopo l'audit, propone la pulizia di ~/.cache con conferma."
    )
    args = parser.parse_args()

    if args.min_gb <= 0:
        parser.error("--min-gb deve essere maggiore di zero")
    if args.inode_top < 1:
        parser.error("--inode-top deve essere almeno 1")

    report_file = None
    original_stdout = sys.stdout
    try:
        if args.report:
            report_path = Path(args.report).expanduser()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_file = report_path.open("w", encoding="utf-8")
            sys.stdout = Tee(original_stdout, report_file)

        print("DISK SCOUT 2.1 — AUDIT DISCO E INODE PER DEBIAN E DERIVATE")
        print(f"Data: {datetime.now().astimezone().isoformat(timespec='seconds')}")
        print(f"Utente: {os.environ.get('USER', '(sconosciuto)')}")
        print(f"Home: {HOME}")
        print("Modalità audit: scansioni in sola lettura; pulizie solo con opzione e conferma.")

        disk_overview()
        storage_audit()
        roots = [HOME]
        # Additional roots are scanned read-only; inode scan avoids crossing
        # filesystem boundaries below each selected root.
        for path in (Path("/var"), Path("/opt"), Path("/tmp"),
                     Path("/usr/local"), Path("/mnt"), Path("/media")):
            if path.exists():
                roots.append(path)
        inode_filesystems()
        if not args.skip_inode_scan:
            inode_directory_audit(roots, top_n=args.inode_top)
        else:
            print("\nScansione ricorsiva inode saltata su richiesta.")
        scan_large_and_special_files(roots, int(args.min_gb * GIB))
        container_audit()
        vm_audit()
        ai_audit()

        if args.cleanup_apt_cache:
            cleanup_apt_cache()
        if args.cleanup_user_cache:
            cleanup_user_cache()

        section("FINE AUDIT")
        print("Nessuna VM, immagine container, volume o modello AI è stata rimossa.")
        if args.report:
            print(f"Report richiesto: {Path(args.report).expanduser()}")
    finally:
        sys.stdout = original_stdout
        if report_file:
            report_file.close()


class Tee:
    """Write console output and a report file at the same time."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


if __name__ == "__main__":
    main()
