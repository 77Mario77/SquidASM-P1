"""Esperimenti sul protocollo P1.

Uso:
    python run_experiments.py abort    [--quick]   # probabilita' di aborto al variare di L (e di r in analisi)
    python run_experiments.py noise    [--quick]   # effetto del rumore (fedelta' dei link, gate)
    python run_experiments.py forgery  [--quick]   # tentativo di forgery di Bob
    python run_experiments.py all      [--quick]

I dati grezzi finiscono in results/raw.csv (una riga per ogni esecuzione completa
del protocollo). Le soglie r, s_a, s_v NON sono fissate qui: il programma salva i
conteggi grezzi (qubit inoltrati, mismatch) e analyze.py applica le soglie dopo.
Se si interrompe, rilanciando si riparte dai batch non ancora fatti.
"""
import argparse
import csv
import random
import time
from pathlib import Path

from squidasm.run.stack.config import StackNetworkConfig
from squidasm.run.stack.run import run

from application import AliceProgram, BobProgram, CharlieProgram

BASE = Path(__file__).resolve().parent
RESULTS_DIR = BASE / "results"
CONFIG_DIR = RESULTS_DIR / "configs"
RAW = RESULTS_DIR / "raw.csv"

FIELDS = [
    "tag", "condition", "scenario", "L", "message", "run",
    "fidelity", "gate1", "gate2",
    "b_mismatch", "b_records", "b_recv0", "b_recv1", "b_sent0", "b_sent1",
    "c_mismatch", "c_records", "c_recv0", "c_recv1", "c_sent0", "c_sent1",
]

# parametri del caso rumoroso di riferimento (stessi di config_noisy.yaml)
BASE_FIDELITY = 0.9
BASE_GATE1 = 0.01
BASE_GATE2 = 0.1


# ----------------------------------------------------------------------
def noisy_config_file(fidelity, gate1, gate2, prob_success=0.8):
    """Scrive un file yaml con i parametri di rumore richiesti (stessa
    struttura di config_noisy.yaml) e ne restituisce il percorso."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / f"noisy_F{fidelity}_g{gate1}_{gate2}.yaml"
    if path.exists():
        return path
    text = f"""qdevice_cfg: &qdevice_cfg
  num_qubits: 2
  T1: 1000000000
  T2: 100000000
  init_time: 10000
  single_qubit_gate_time: 1000
  two_qubit_gate_time: 100000
  measure_time: 10000
  single_qubit_gate_depolar_prob: {gate1}
  two_qubit_gate_depolar_prob: {gate2}

stacks:
  - name: Alice
    qdevice_typ: generic
    qdevice_cfg:
      <<: *qdevice_cfg
  - name: Bob
    qdevice_typ: generic
    qdevice_cfg:
      <<: *qdevice_cfg
  - name: Charlie
    qdevice_typ: generic
    qdevice_cfg:
      <<: *qdevice_cfg

link_cfg: &link_cfg
  fidelity: {fidelity}
  prob_success: {prob_success}
  t_cycle: 100000

links:
  - stack1: Alice
    stack2: Bob
    typ: depolarise
    cfg:
      <<: *link_cfg
  - stack1: Alice
    stack2: Charlie
    typ: depolarise
    cfg:
      <<: *link_cfg
  - stack1: Bob
    stack2: Charlie
    typ: depolarise
    cfg:
      <<: *link_cfg

clinks:
  - stack1: Alice
    stack2: Bob
    typ: default
    cfg:
      delay: 5000
  - stack1: Alice
    stack2: Charlie
    typ: default
    cfg:
      delay: 10000
  - stack1: Bob
    stack2: Charlie
    typ: default
    cfg:
      delay: 10000
"""
    path.write_text(text)
    return path


def done_tags():
    if not RAW.exists():
        return set()
    with open(RAW, newline="") as f:
        return {row["tag"] for row in csv.DictReader(f)}


def append_rows(rows):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    new = not RAW.exists()
    with open(RAW, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def set_seed(seed):
    random.seed(seed)
    try:
        import netsquid as ns
        ns.set_random_state(seed)
    except Exception:
        pass


def run_batch(condition, scenario, L, n_runs, fidelity=None, gate1=None, gate2=None, seed0=1000):
    """Esegue n_runs volte il protocollo (meta' con m=0, meta' con m=1)."""
    if condition == "ideal":
        config_path = BASE / "config_ideal.yaml"
        fidelity, gate1, gate2 = 1.0, 0.0, 0.0
    else:
        fidelity = BASE_FIDELITY if fidelity is None else fidelity
        gate1 = BASE_GATE1 if gate1 is None else gate1
        gate2 = BASE_GATE2 if gate2 is None else gate2
        config_path = noisy_config_file(fidelity, gate1, gate2)

    tag = f"{condition}|{scenario}|L={L}|F={fidelity}|g1={gate1}|g2={gate2}|n={n_runs}"
    if tag in done_tags():
        print(f"  (gia' fatto) {tag}")
        return

    config = StackNetworkConfig.from_file(str(config_path))
    rows = []
    t0 = time.time()
    for message in (0, 1):
        n = n_runs // 2 if message == 0 else n_runs - n_runs // 2
        set_seed(seed0 + 17 * L + 5 * message)
        programs = {
            # sa e sv qui servono solo per l'esito "accepted" salvato dal
            # programma; le soglie usate nei grafici si scelgono in analyze.py
            "Alice": AliceProgram(num_bits=L, message_bit=message, scenario=scenario),
            "Bob": BobProgram(num_bits=L, sa=0.0, sv=0.05, r=0.1, forge=(scenario == "forgery")),
            "Charlie": CharlieProgram(num_bits=L, sa=0.0, sv=0.05, r=0.1),
        }
        _, bob, charlie = run(config=config, programs=programs, num_times=n)
        for k in range(n):
            b, c = bob[k], charlie[k]
            rows.append({
                "tag": tag, "condition": condition, "scenario": scenario, "L": L,
                "message": message, "run": k,
                "fidelity": fidelity, "gate1": gate1, "gate2": gate2,
                "b_mismatch": b["mismatches"], "b_records": b["records_checked"],
                "b_recv0": b["n_recv"][0], "b_recv1": b["n_recv"][1],
                "b_sent0": b["n_sent"][0], "b_sent1": b["n_sent"][1],
                "c_mismatch": c["mismatches"], "c_records": c["records_checked"],
                "c_recv0": c["n_recv"][0], "c_recv1": c["n_recv"][1],
                "c_sent0": c["n_sent"][0], "c_sent1": c["n_sent"][1],
            })
    append_rows(rows)
    print(f"  fatto {tag}  ({len(rows)} esecuzioni, {time.time() - t0:.1f} s)", flush=True)


# ----------------------------------------------------------------------
def exp_abort(quick):
    # L piccoli e medi con tante ripetizioni; il caso rumoroso (l'aborto non
    # dipende dal rumore) solo per alcuni L, per risparmiare tempo.
    lengths = [8, 16, 32, 48, 64] if quick else [8, 16, 24, 32, 48, 64, 96]
    noisy_lengths = [16, 32, 64]
    n_runs = 20 if quick else 200
    print("== Probabilita' di aborto: ideale e rumoroso, autentico ==")
    for L in lengths:
        run_batch("ideal", "authentic", L, n_runs)
    for L in noisy_lengths:
        run_batch("noisy", "authentic", L, n_runs // 2)


def exp_noise(quick):
    L = 32
    n_runs = 20 if quick else 60
    fidelities = [1.0, 0.97, 0.9, 0.8] if quick else [1.0, 0.99, 0.97, 0.95, 0.92, 0.9, 0.85, 0.8, 0.75]
    gates = [0.0, 0.01, 0.05] if quick else [0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1]
    print("== Rumore: fedelta' dei link (gate come nel caso di riferimento) ==")
    for F in fidelities:
        run_batch("noisy", "authentic", L, n_runs, fidelity=F)
    print("== Rumore: depolarizzazione dei gate (link come nel caso di riferimento) ==")
    for g in gates:
        # la depolarizzazione a due qubit e' tenuta 10 volte quella a un qubit,
        # come nella configurazione di riferimento (0.01 e 0.1)
        run_batch("noisy", "authentic", L, n_runs, gate1=g, gate2=min(1.0, 10 * g))


def exp_forgery(quick):
    lengths = [8, 16, 32, 64] if quick else [8, 16, 32, 64]
    n_runs = 20 if quick else 100
    print("== Forgery di Bob ==")
    for L in lengths:
        for cond in ("ideal", "noisy"):
            run_batch(cond, "forgery", L, n_runs)
    # per confronto servono anche i messaggi autentici con le stesse L (gia' fatti in abort
    # per L=8,16,32,64 nel caso ideale e L=16,32,64 in quello rumoroso)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["abort", "noise", "forgery", "all"])
    ap.add_argument("--quick", action="store_true",
                    help="poche esecuzioni, solo per controllare che giri tutto")
    a = ap.parse_args()
    if a.what in ("abort", "all"):
        exp_abort(a.quick)
    if a.what in ("noise", "all"):
        exp_noise(a.quick)
    if a.what in ("forgery", "all"):
        exp_forgery(a.quick)


if __name__ == "__main__":
    main()
