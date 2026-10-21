"""Legge results/raw.csv e produce i grafici in figures/.

Le soglie r, s_a, s_v si applicano qui ai conteggi grezzi salvati da run_experiments.py.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from application import abort_limits

BASE = Path(__file__).resolve().parent
RAW = BASE / "results" / "raw.csv"
FIG = BASE / "figures"
FIG.mkdir(exist_ok=True)

INT_FIELDS = ["L", "message", "run", "b_mismatch", "b_records", "b_recv0", "b_recv1",
              "b_sent0", "b_sent1", "c_mismatch", "c_records", "c_recv0", "c_recv1",
              "c_sent0", "c_sent1"]
FLOAT_FIELDS = ["fidelity", "gate1", "gate2"]

BASE_F, BASE_G = 0.9, 0.01


def load():
    rows = []
    with open(RAW, newline="") as f:
        for r in csv.DictReader(f):
            for k in INT_FIELDS:
                r[k] = int(r[k])
            for k in FLOAT_FIELDS:
                r[k] = float(r[k])
            rows.append(r)
    return rows


def select(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]



def is_abort(row, r):
    low, high = abort_limits(row["L"], r)
    counts = [row["b_recv0"], row["b_recv1"], row["c_recv0"], row["c_recv1"]]
    return any(not (low <= n <= high) for n in counts)


def abort_prob_sim(rows, r):
    if not rows:
        return float("nan"), 0.0
    p = sum(is_abort(x, r) for x in rows) / len(rows)
    err = math.sqrt(max(p * (1 - p), 1e-12) / len(rows))
    return p, err


def abort_prob_exact(L, r):
    """Quattro contatori indipendenti ~ Binomiale(L, 1/2): due per ciascun
    destinatario (messaggi 0 e 1). Aborto se almeno uno e' fuori da [low, high]."""
    low, high = abort_limits(L, r)
    out = sum(math.comb(L, k) for k in range(L + 1) if not (low <= k <= high)) / 2 ** L
    return 1 - (1 - out) ** 4


def hoeffding(L, r):
    return min(1.0, 4 * 2 * math.exp(-2 * r * r * L))


def accepted_bob(row, r, sa):
    return (not is_abort(row, r)) and row["b_mismatch"] <= int(sa * row["L"])


def accepted_charlie(row, r, sv):
    return (not is_abort(row, r)) and row["c_mismatch"] <= int(sv * row["L"])


def frac(rows, fn):
    return sum(fn(x) for x in rows) / len(rows) if rows else float("nan")


def _yerr(pts):
    """Barre d'errore asimmetriche: la parte inferiore non supera il 90% del valore (scala log)."""
    return [[min(p[2], 0.9 * p[1]) for p in pts], [p[2] for p in pts]]



def fig_abort_vs_L(rows):
    ideal = select(rows, condition="ideal", scenario="authentic")
    Ls = sorted({x["L"] for x in ideal})
    if not Ls:
        return
    rs = [0.1, 0.15, 0.2, 0.25, 0.3]
    Lfine = np.arange(min(Ls), max(Ls) + 1)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for i, r in enumerate(rs):
        col = f"C{i}"
        ax.plot(Lfine, [abort_prob_exact(int(L), r) for L in Lfine], "-", color=col, lw=1, alpha=.8)
        ax.plot(Lfine, [hoeffding(int(L), r) for L in Lfine], ":", color=col, lw=1)
        pts = [(L, *abort_prob_sim(select(ideal, L=L), r)) for L in Ls]
        pts = [p for p in pts if p[1] > 0]
        if pts:
            ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=_yerr(pts),
                        fmt="o", color=col, ms=4, capsize=2, label=f"r = {r}")
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 1.5)
    ax.set_xlabel("lunghezza della firma L")
    ax.set_ylabel("probabilita' di aborto")
    ax.set_title("Caso ideale: aborto al variare di L")
    ax.plot([], [], "-", color="gray", label="calcolo esatto (binomiale)")
    ax.plot([], [], ":", color="gray", label="limite di Hoeffding")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3, which="both")
    fig.tight_layout()
    fig.savefig(FIG / "abort_vs_L_ideale.png", dpi=170)
    plt.close(fig)


def fig_abort_vs_r(rows):
    ideal = select(rows, condition="ideal", scenario="authentic")
    Ls = sorted({x["L"] for x in ideal})
    chosen = [L for L in (16, 32, 64, 128) if L in Ls]
    if not chosen:
        return
    rgrid = np.linspace(0.02, 0.4, 80)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for i, L in enumerate(chosen):
        col = f"C{i}"
        ax.plot(rgrid, [abort_prob_exact(L, r) for r in rgrid], "-", color=col, lw=1, alpha=.8)
        rs = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
        pts = [(r, *abort_prob_sim(select(ideal, L=L), r)) for r in rs]
        pts = [p for p in pts if p[1] > 0]
        if pts:
            ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=_yerr(pts),
                        fmt="o", color=col, ms=4, capsize=2, label=f"L = {L}")
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 1.5)
    ax.set_xlabel("soglia r")
    ax.set_ylabel("probabilita' di aborto")
    ax.set_title("Caso ideale: aborto al variare di r")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3, which="both")
    fig.tight_layout()
    fig.savefig(FIG / "abort_vs_r_ideale.png", dpi=170)
    plt.close(fig)


def fig_abort_ideal_vs_noisy(rows):
    Ls = sorted({x["L"] for x in select(rows, scenario="authentic", condition="noisy")
                 if x["fidelity"] == BASE_F and x["gate1"] == BASE_G})
    if not Ls:
        return
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, r in zip(axs, (0.1, 0.2)):
        for cond, mk in (("ideal", "o"), ("noisy", "s")):
            sel = select(rows, condition=cond, scenario="authentic")
            if cond == "noisy":
                sel = [x for x in sel if x["fidelity"] == BASE_F and x["gate1"] == BASE_G]
            pts = [(L, *abort_prob_sim([x for x in sel if x["L"] == L], r)) for L in Ls]
            pts = [p for p in pts if p[1] > 0]
            if pts:
                ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=_yerr(pts),
                            fmt=mk, capsize=2, ms=4, label="ideale" if cond == "ideal" else "rumoroso")
        Lfine = np.arange(min(Ls), max(Ls) + 1)
        ax.plot(Lfine, [abort_prob_exact(int(L), r) for L in Lfine], "k-", lw=1, label="esatto")
        ax.set_yscale("log"); ax.set_ylim(1e-4, 1.5)
        ax.set_xlabel("L"); ax.set_title(f"r = {r}")
        ax.grid(alpha=.3, which="both"); ax.legend(fontsize=8)
    axs[0].set_ylabel("probabilita' di aborto")
    fig.suptitle("Aborto: ideale e rumoroso a confronto")
    fig.tight_layout()
    fig.savefig(FIG / "abort_ideale_vs_rumoroso.png", dpi=170)
    plt.close(fig)


def fig_mismatch_hist(rows):
    L = 32
    ideal = select(rows, condition="ideal", scenario="authentic", L=L)
    noisy = [x for x in select(rows, condition="noisy", scenario="authentic", L=L)
             if x["fidelity"] == BASE_F and x["gate1"] == BASE_G]
    if not ideal or not noisy:
        return
    fig, axs = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, key, name in zip(axs, ("b_mismatch", "c_mismatch"), ("Bob", "Charlie")):
        mx = max(max(x[key] for x in ideal), max(x[key] for x in noisy), 1)
        bins = np.arange(-0.5, mx + 1.5)
        ax.hist([x[key] for x in ideal], bins=bins, alpha=.6, label="ideale", density=True)
        ax.hist([x[key] for x in noisy], bins=bins, alpha=.6, label="rumoroso", density=True)
        ax.set_xlabel(f"numero di mismatch ({name}), L = {L}")
        ax.legend(fontsize=8)
    axs[0].set_ylabel("frequenza")
    fig.suptitle("Messaggio autentico: mismatch")
    fig.tight_layout()
    fig.savefig(FIG / "mismatch_istogrammi.png", dpi=170)
    plt.close(fig)


def _noise_sweep(rows, param, xlabel, fname, title, r=0.25, thresholds=((0.05, 0.10), (0.10, 0.15), (0.15, 0.25))):
    L = 32
    sel = [x for x in select(rows, condition="noisy", scenario="authentic", L=L)]
    if param == "fidelity":
        sel = [x for x in sel if x["gate1"] == BASE_G]
    else:
        sel = [x for x in sel if x["fidelity"] == BASE_F]
    # il caso ideale e' il punto limite (F = 1, nessun errore sui gate)
    xs = sorted({x[param] for x in sel})
    if len(xs) < 2:
        return
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.2))
    mb = [np.mean([x["b_mismatch"] / L for x in sel if x[param] == v]) for v in xs]
    mc = [np.mean([x["c_mismatch"] / L for x in sel if x[param] == v]) for v in xs]
    axs[0].plot(xs, mb, "o-", label="Bob")
    axs[0].plot(xs, mc, "s-", label="Charlie")
    axs[0].set_ylabel("mismatch / L (media)")
    axs[0].legend(fontsize=8)
    for sa, sv in thresholds:
        lab = f"s_a={sa}, s_v={sv}"
        axs[1].plot(xs, [frac([x for x in sel if x[param] == v], lambda x: accepted_bob(x, r, sa)) for v in xs],
                    "o-", label=lab)
        axs[2].plot(xs, [frac([x for x in sel if x[param] == v], lambda x: accepted_charlie(x, r, sv)) for v in xs],
                    "o-", label=lab)
    axs[1].set_ylabel("probabilita' che Bob accetti")
    axs[2].set_ylabel("probabilita' che Charlie accetti")
    for ax in axs:
        ax.set_xlabel(xlabel)
        ax.grid(alpha=.3)
        if param == "fidelity":
            ax.invert_xaxis()
        if param == "gate1":
            ax.set_xscale("symlog", linthresh=1e-3)
        ax.axvline(BASE_F if param == "fidelity" else BASE_G, color="gray", ls="--", lw=1)
    axs[1].legend(fontsize=8)
    axs[1].set_ylim(-0.05, 1.05); axs[2].set_ylim(-0.05, 1.05)
    fig.suptitle(f"{title} (L = {L}, r = {r}); tratteggio = valore di riferimento")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=170)
    plt.close(fig)


def _noisy_ref(rows, scenario, L):
    return [x for x in select(rows, condition="noisy", scenario=scenario, L=L)
            if x["fidelity"] == BASE_F and x["gate1"] == BASE_G]


def fig_mismatch_vs_L(rows):
    """Mismatch/L di Charlie (media e deviazione standard) al variare di L."""
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for label, cond, scen, mk in (("ideale, autentico", "ideal", "authentic", "o"),
                                  ("rumoroso, autentico", "noisy", "authentic", "s"),
                                  ("ideale, forgery", "ideal", "forgery", "^"),
                                  ("rumoroso, forgery", "noisy", "forgery", "v")):
        Ls = sorted({x["L"] for x in select(rows, condition=cond, scenario=scen)})
        m, sd, xs = [], [], []
        for L in Ls:
            sel = select(rows, condition=cond, scenario=scen, L=L) if cond == "ideal" else _noisy_ref(rows, scen, L)
            if not sel:
                continue
            v = [x["c_mismatch"] / L for x in sel]
            xs.append(L); m.append(np.mean(v)); sd.append(np.std(v))
        if xs:
            ax.errorbar(xs, m, yerr=sd, fmt=mk + "-", capsize=3, ms=5, label=label)
    ax.set_xlabel("L"); ax.set_ylabel("mismatch / L visti da Charlie")
    ax.set_title("Mismatch di Charlie: autentico e forgery")
    ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "mismatch_vs_L.png", dpi=170); plt.close(fig)


def fig_thresholds(rows):
    """Probabilita' che Charlie accetti in funzione della soglia s_v (senza considerare l'aborto)."""
    Ls = [L for L in (32, 64) if _noisy_ref(rows, "forgery", L) and _noisy_ref(rows, "authentic", L)]
    if not Ls:
        return
    svs = np.linspace(0, 0.4, 161)
    fig, axs = plt.subplots(1, len(Ls), figsize=(5.8 * len(Ls), 4.4), sharey=True)
    axs = np.atleast_1d(axs)
    for ax, L in zip(axs, Ls):
        curves = (("autentico, ideale", select(rows, condition="ideal", scenario="authentic", L=L), "C0", "-"),
                  ("autentico, rumoroso", _noisy_ref(rows, "authentic", L), "C1", "-"),
                  ("forgery, ideale", select(rows, condition="ideal", scenario="forgery", L=L), "C0", "--"),
                  ("forgery, rumoroso", _noisy_ref(rows, "forgery", L), "C1", "--"))
        for lab, sel, col, ls in curves:
            if sel:
                ax.plot(svs, [np.mean([x["c_mismatch"] <= int(sv * L) for x in sel]) for sv in svs],
                        ls, color=col, label=lab)
        ax.axvline((1 - 2 * 0.1) / 16, color="gray", ls=":", lw=1)
        ax.text((1 - 2 * 0.1) / 16 + 0.005, 0.5, "(1-2r)/16, r=0.1", rotation=90, fontsize=7, color="gray", va="center")
        ax.set_xlabel("soglia di verifica s_v"); ax.set_title(f"L = {L}")
        ax.grid(alpha=.3)
    axs[0].set_ylabel("probabilita' che Charlie accetti")
    axs[0].legend(fontsize=8)
    fig.suptitle("Accettazione di Charlie al variare di s_v (aborto escluso)")
    fig.tight_layout(); fig.savefig(FIG / "soglia_sv.png", dpi=170); plt.close(fig)


def fig_forgery(rows):
    """Accettazione della firma al variare di L, per due soglie s_v."""
    fig, axs = plt.subplots(1, 2, figsize=(10.5, 4.3), sharey=True)
    for ax, sv in zip(axs, (0.10, 0.15)):
        for label, cond, scen, mk, ls in (("forgery, ideale", "ideal", "forgery", "^", "--"),
                                          ("forgery, rumoroso", "noisy", "forgery", "v", "--"),
                                          ("autentico, rumoroso", "noisy", "authentic", "s", "-")):
            Ls = sorted({x["L"] for x in select(rows, condition=cond, scenario=scen)})
            xs, ys = [], []
            for L in Ls:
                sel = select(rows, condition=cond, scenario=scen, L=L) if cond == "ideal" else _noisy_ref(rows, scen, L)
                if sel:
                    xs.append(L); ys.append(np.mean([x["c_mismatch"] <= int(sv * L) for x in sel]))
            ax.plot(xs, ys, ls, marker=mk, label=label)
        ax.set_xlabel("L"); ax.set_title(f"s_v = {sv}"); ax.grid(alpha=.3)
    axs[0].set_ylabel("probabilita' che Charlie accetti")
    axs[0].legend(fontsize=8)
    fig.suptitle("Forgery di Bob contro messaggio autentico (aborto escluso)")
    fig.tight_layout(); fig.savefig(FIG / "forgery.png", dpi=170); plt.close(fig)


def main():
    if not RAW.exists():
        raise SystemExit("Manca results/raw.csv: prima lancia run_experiments.py")
    rows = load()
    fig_abort_vs_L(rows)
    fig_abort_vs_r(rows)
    fig_abort_ideal_vs_noisy(rows)
    fig_mismatch_hist(rows)
    _noise_sweep(rows, "fidelity", "fedelta' dei link", "rumore_fedelta.png", "Effetto della fedelta' dei link")
    _noise_sweep(rows, "gate1", "depolarizzazione gate a un qubit", "rumore_gate.png", "Effetto del rumore sui gate")
    fig_mismatch_vs_L(rows)
    fig_thresholds(rows)
    fig_forgery(rows)
    print("Grafici salvati in", FIG)


if __name__ == "__main__":
    main()
