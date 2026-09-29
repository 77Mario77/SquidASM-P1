from squidasm.sim.stack.program import Program, ProgramContext, ProgramMeta
import random


STATE_NAMES = {
    0: "|0>",
    1: "|1>",
    2: "|+>",
    3: "|->",
}


def state_name(state):
    return STATE_NAMES[state]


def measure_bb84_state(state):
    """
    Misura idealmente uno stato BB84.

    0 = |0>
    1 = |1>
    2 = |+>
    3 = |->

    Restituisce lo stato che viene escluso dalla misura.
    """

    basis = random.randint(0, 1)

    if basis == 0:
        # Misura nella base Z
        if state == 0:
            result = 0
            eliminated_state = 1

        elif state == 1:
            result = 1
            eliminated_state = 0

        else:
            # |+> o |-> misurati in Z:
            # risultato casuale
            result = random.randint(0, 1)

            if result == 0:
                eliminated_state = 1
            else:
                eliminated_state = 0

        basis_name = "Z"

    else:
        # Misura nella base X
        if state == 2:
            result = 0
            eliminated_state = 3

        elif state == 3:
            result = 1
            eliminated_state = 2

        else:
            # |0> o |1> misurati in X:
            # risultato casuale
            result = random.randint(0, 1)

            if result == 0:
                eliminated_state = 3
            else:
                eliminated_state = 2

        basis_name = "X"

    print(
        f"      Measurement: "
        f"state={state_name(state)}, "
        f"basis={basis_name}, "
        f"result={result}, "
        f"eliminated={state_name(eliminated_state)}"
    )

    return eliminated_state


class AliceProgram(Program):

    PEERS = ["Bob", "Charlie"]

    def __init__(self, signatures):
        self.signatures = signatures

    @property
    def meta(self) -> ProgramMeta:
        return ProgramMeta(
            name="alice_p1",
            csockets=["Bob", "Charlie"],
            epr_sockets=[],
            max_qubits=1,
        )

    def run(self, context: ProgramContext):


        print("\nAlice genera le quantum signatures")

        for k in [0, 1]:

            print(f"\nSignature per messaggio k={k}:")

            for i, state in enumerate(self.signatures[k]):

                print(
                    f"  posizione {i:2d}: "
                    f"{state_name(state)}"
                )

        print("\nAlice ha generato le due copie logiche")
        print("delle quantum signatures.")

        # Sincronizzazione con Bob e Charlie.
        context.csockets["Bob"].send("START")
        context.csockets["Charlie"].send("START")

        # Aspettiamo che entrambi abbiano terminato
        # la loro parte del protocollo.
        yield from context.csockets["Bob"].recv()
        yield from context.csockets["Charlie"].recv()

        print("\nAlice: Bob e Charlie hanno terminato.")

        return


class BobProgram(Program):

    PEERS = ["Alice"]

    def __init__(
        self,
        signatures,
        choices_bob,
        choices_charlie,
        r,
    ):
        self.signatures = signatures
        self.choices_bob = choices_bob
        self.choices_charlie = choices_charlie
        self.r = r

    @property
    def meta(self) -> ProgramMeta:
        return ProgramMeta(
            name="bob_p1",
            csockets=["Alice"],
            epr_sockets=[],
            max_qubits=1,
        )

    def run(self, context: ProgramContext):

        # Aspetta che Alice inizi.
        yield from context.csockets["Alice"].recv()

        print("\n")
        print("BOB")

        eliminated_states = {
            0: [[] for _ in self.signatures[0]],
            1: [[] for _ in self.signatures[1]],
        }

        received_from_charlie = {
            0: 0,
            1: 0,
        }

        print("\nBob decide KEEP/FORWARD e misura")

        for k in [0, 1]:

            print(f"\n--- Messaggio k={k} ---")

            for i, state in enumerate(self.signatures[k]):

                bob_keep = self.choices_bob[k][i] == 0
                charlie_forward = self.choices_charlie[k][i] == 1

                print(
                    f"\n  posizione {i:2d}: "
                    f"Bob={'KEEP' if bob_keep else 'FORWARD'}, "
                    f"Charlie="
                    f"{'FORWARD' if charlie_forward else 'KEEP'}"
                )

                # Bob misura sempre la propria copia
                # se decide KEEP.
                if bob_keep:

                    eliminated = measure_bb84_state(state)

                    eliminated_states[k][i].append(
                        eliminated
                    )

                # Se Charlie fa FORWARD, Bob riceve
                # la copia di Charlie e la misura.
                if charlie_forward:

                    received_from_charlie[k] += 1

                    eliminated = measure_bb84_state(state)

                    eliminated_states[k][i].append(
                        eliminated
                    )

        # Controllo numero di stati
        lower_bound = int(
            len(self.signatures[0]) * (0.5 - self.r)
        )

        upper_bound = int(
            len(self.signatures[0]) * (0.5 + self.r)
        )

        print("\n")
        print("CONTROLLO NUMERO DI STATI RICEVUTI")

        for k in [0, 1]:

            received = received_from_charlie[k]

            print(
                f"Bob - k={k}: "
                f"ricevuti {received} stati "
                f"(limiti: {lower_bound}-{upper_bound})"
            )

            if received < lower_bound or received > upper_bound:

                print(
                    f"Bob: ABORT per k={k}"
                )

            else:

                print(
                    f"Bob: controllo superato per k={k}"
                )

        print("\nSTATI ESCLUSI DA BOB:")

        for k in [0, 1]:

            print(f"\nk={k}")

            for i, eliminated in enumerate(
                eliminated_states[k]
            ):

                print(
                    f"  posizione {i:2d}: "
                    f"{[state_name(x) for x in eliminated]}"
                )

        # Comunica ad Alice che ha terminato.
        context.csockets["Alice"].send("DONE_BOB")

        return


class CharlieProgram(Program):

    PEERS = ["Alice"]

    def __init__(
        self,
        signatures,
        choices_bob,
        choices_charlie,
        r,
    ):
        self.signatures = signatures
        self.choices_bob = choices_bob
        self.choices_charlie = choices_charlie
        self.r = r

    @property
    def meta(self) -> ProgramMeta:
        return ProgramMeta(
            name="charlie_p1",
            csockets=["Alice"],
            epr_sockets=[],
            max_qubits=1,
        )

    def run(self, context: ProgramContext):

        # Aspetta che Alice inizi.
        yield from context.csockets["Alice"].recv()

        print("\n")
        print("CHARLIE")

        eliminated_states = {
            0: [[] for _ in self.signatures[0]],
            1: [[] for _ in self.signatures[1]],
        }

        received_from_bob = {
            0: 0,
            1: 0,
        }

        print("\nCharlie decide KEEP/FORWARD e misura")

        for k in [0, 1]:

            print(f"\n--- Messaggio k={k} ---")

            for i, state in enumerate(self.signatures[k]):

                charlie_keep = self.choices_charlie[k][i] == 0
                bob_forward = self.choices_bob[k][i] == 1

                print(
                    f"\n  posizione {i:2d}: "
                    f"Charlie="
                    f"{'KEEP' if charlie_keep else 'FORWARD'}, "
                    f"Bob="
                    f"{'FORWARD' if bob_forward else 'KEEP'}"
                )

                # Charlie misura la propria copia
                # se decide KEEP.
                if charlie_keep:

                    eliminated = measure_bb84_state(state)

                    eliminated_states[k][i].append(
                        eliminated
                    )

                # Se Bob fa FORWARD, Charlie riceve
                # la copia di Bob e la misura.
                if bob_forward:

                    received_from_bob[k] += 1

                    eliminated = measure_bb84_state(state)

                    eliminated_states[k][i].append(
                        eliminated
                    )

        # Controllo numero di stati ricevuti
        lower_bound = int(
            len(self.signatures[0]) * (0.5 - self.r)
        )

        upper_bound = int(
            len(self.signatures[0]) * (0.5 + self.r)
        )

        print("\n")
        print("CONTROLLO NUMERO DI STATI RICEVUTI")

        for k in [0, 1]:

            received = received_from_bob[k]

            print(
                f"Charlie - k={k}: "
                f"ricevuti {received} stati "
                f"(limiti: {lower_bound}-{upper_bound})"
            )

            if received < lower_bound or received > upper_bound:

                print(
                    f"Charlie: ABORT per k={k}"
                )

            else:

                print(
                    f"Charlie: controllo superato per k={k}"
                )

        print("\nSTATI ESCLUSI DA CHARLIE:")

        for k in [0, 1]:

            print(f"\nk={k}")

            for i, eliminated in enumerate(
                eliminated_states[k]
            ):

                print(
                    f"  posizione {i:2d}: "
                    f"{[state_name(x) for x in eliminated]}"
                )

        # Comunica ad Alice che ha terminato.
        context.csockets["Alice"].send("DONE_CHARLIE")

        return
