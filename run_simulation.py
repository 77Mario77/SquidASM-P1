import random

from squidasm.run.stack.run import run
from squidasm.run.stack.config import StackNetworkConfig

from application import (
    AliceProgram,
    BobProgram,
    CharlieProgram,
)


#Parametri

L = 20

r = 0.2


#Inizializzo un seme casuale

random.seed(42)


#Generazione Quantum Signatures

signatures = {

    0: [
        random.randint(0, 3)
        for _ in range(L)
    ],

    1: [
        random.randint(0, 3)
        for _ in range(L)
    ],
}

#Bob e Charlie scelgono se mantenere o inoltrare lo stato
# 0 = KEEP
# 1 = FORWARD

choices_bob = {

    0: [
        random.randint(0, 1)
        for _ in range(L)
    ],

    1: [
        random.randint(0, 1)
        for _ in range(L)
    ],
}


choices_charlie = {

    0: [
        random.randint(0, 1)
        for _ in range(L)
    ],

    1: [
        random.randint(0, 1)
        for _ in range(L)
    ],
}



print("SIMULAZIONE P1")

print(f"\nL = {L}")
print(f"r = {r}")

print("\nScelte Bob:")
for k in [0, 1]:
    print(f"  k={k}: {choices_bob[k]}")

print("\nScelte Charlie:")
for k in [0, 1]:
    print(f"  k={k}: {choices_charlie[k]}")

#Configurazione rete

cfg = StackNetworkConfig.from_file(
    "config.yaml"
)


#Programmi 

alice = AliceProgram(
    signatures=signatures
)


bob = BobProgram(
    signatures=signatures,
    choices_bob=choices_bob,
    choices_charlie=choices_charlie,
    r=r,
)


charlie = CharlieProgram(
    signatures=signatures,
    choices_bob=choices_bob,
    choices_charlie=choices_charlie,
    r=r,
)


#Inizio simulazione

print("\n")
print("AVVIO SIMULAZIONE")


run(
    config=cfg,
    programs={
        "Alice": alice,
        "Bob": bob,
        "Charlie": charlie,
    },
)

print("\n")
print("SIMULAZIONE TERMINATA")
