"""How evenly name detection works across naming traditions - and what it wrongly takes.

Neutral cannot remove a name it does not see, so a detector that finds some traditions'
names less often protects those people less. This measures it the way the project
measures a model: identical sentences, only the name changes. It also measures the
opposite failure, on sentences full of company, product and place names that must not be
replaced, because a detector made generous enough to find every name will start finding
names that are not there.

Run with `make names`. No model is called.
"""

from __future__ import annotations

from collections.abc import Callable

FRAMES = [
    "Assess {name} for promotion.",
    "Write a performance review for {name}.",
    "Should {name} be promoted this cycle?",
    "Give feedback on {name}'s work this quarter.",
    "My colleague {name} keeps missing deadlines. How do I raise it?",
    "{name} joined the team in March and has shipped two features.",
    "Draft a rejection email to {name}.",
    "Compare {name} with the other candidate for the analyst role.",
    "{name} says the project is behind schedule.",
    "How should I tell {name} that the budget was cut?",
]

# Ten names per tradition. Chosen to be ordinary in each tradition, not rare - the test is
# whether a common name from that tradition is found, not an unusual one.
NAMES = {
    "Anglo": [
        "Emily Carter",
        "Oliver Hayes",
        "Sarah Bennett",
        "James Walker",
        "Rachel Nolan",
        "Thomas Reed",
        "Hannah Brooks",
        "Daniel Price",
        "Laura Mitchell",
        "George Turner",
    ],
    "Hispanic / Latino": [
        "Maria Garcia",
        "Carlos Hernandez",
        "Lucia Morales",
        "Diego Ramirez",
        "Sofia Torres",
        "Javier Castillo",
        "Ana Lopez",
        "Mateo Sanchez",
        "Valentina Cruz",
        "Luis Ortega",
    ],
    "Slavic": [
        "Tomasz Kowalski",
        "Anna Nowak",
        "Dmitri Volkov",
        "Olga Petrova",
        "Pavel Novak",
        "Katarzyna Wisniewska",
        "Ivan Sokolov",
        "Marta Horvat",
        "Sergei Ivanov",
        "Irena Kovac",
    ],
    "South Asian": [
        "Priya Raman",
        "Arjun Mehta",
        "Ananya Iyer",
        "Rahul Sharma",
        "Deepa Nair",
        "Vikram Singh",
        "Kavya Reddy",
        "Sanjay Gupta",
        "Meera Pillai",
        "Rohan Das",
    ],
    "Arabic / Middle Eastern": [
        "Omar Haddad",
        "Layla Nasser",
        "Youssef Khalil",
        "Fatima Al-Sayed",
        "Karim Mansour",
        "Noor Hamdan",
        "Tariq Aziz",
        "Rania Saleh",
        "Hassan Farouk",
        "Samira Qasim",
    ],
    "East Asian": [
        "Wei Zhang",
        "Min-ji Park",
        "Hiroshi Tanaka",
        "Mei Lin",
        "Jun Wang",
        "Seo-yeon Kim",
        "Kenji Watanabe",
        "Xiu Chen",
        "Ji-ho Lee",
        "Yuki Sato",
    ],
    "African": [
        "Chidi Okonkwo",
        "Kwame Mensah",
        "Amara Nwosu",
        "Tendai Moyo",
        "Abebe Tesfaye",
        "Ngozi Adeyemi",
        "Kofi Boateng",
        "Zanele Dlamini",
        "Oluwaseun Bello",
        "Wanjiru Kamau",
    ],
}

# Sentences that name no person at all. Every capitalised word here must survive.
NO_PEOPLE = [
    "Review our migration from MySQL to Postgres.",
    "Should we use React or Svelte for the dashboard?",
    "Assess Kubernetes for our deployment pipeline.",
    "Write a product description for Notion.",
    "Compare Stripe with Adyen for payments in Europe.",
    "Give feedback on Figma's new auto-layout feature.",
    "Draft an email to Deloitte about the audit timeline.",
    "Summarise the Q3 results for Unilever.",
    "How should Shopify merchants handle chargebacks?",
    "Is Terraform better than Pulumi for a small team?",
    "Our office in Lagos needs a new lease. Draft a note to the landlord.",
    "Write a performance review template for the Nairobi team.",
    "Should we expand to Tokyo or Seoul next year?",
    "Plan a team offsite in Accra for October.",
    "Evaluate Oracle's pricing for the data warehouse.",
    "Explain how Kafka handles consumer groups.",
    "Is Salesforce worth it for a ten-person sales team?",
    "Write release notes for version 2 of Atlas.",
    "Compare Zoom with Teams for all-hands meetings.",
    "Assess the Mandarin localisation of the onboarding flow.",
    # Two capitalised words, like a full name - the hard cases for a generous detector.
    "Assess Google Cloud for our deployment pipeline.",
    "Compare Deutsche Bank with Goldman Sachs for the bond issue.",
    "Write a performance review template for the San Francisco office.",
    "Draft an email to Hugging Face about the model licence.",
    "Should we host on Amazon Web Services or Microsoft Azure?",
    "Give feedback on Visual Studio's new debugger.",
    "Review the contract with Morgan Stanley before Friday.",
    "Tell New York that the launch moved to June.",
]


def recall_by_tradition(detect: Callable[[str], list]) -> dict[str, float]:
    """Share of sentences in which the name was found, per tradition."""
    out = {}
    for tradition, names in NAMES.items():
        hits = 0
        for name in names:
            for frame in FRAMES:
                text = frame.format(name=name)
                found = detect(text)
                if any(name.split()[0] in f.text or name.split()[-1] in f.text for f in found):
                    hits += 1
        out[tradition] = hits / (len(names) * len(FRAMES))
    return out


def false_alarms(detect: Callable[[str], list]) -> list[tuple[str, str]]:
    """(sentence, what was wrongly taken for a name) for every sentence with no people."""
    return [(s, f.text) for s in NO_PEOPLE for f in detect(s)]


def main() -> int:
    from neutral.detect import detect_names_local

    recall = recall_by_tradition(detect_names_local)
    print("\n  Names found, by tradition (identical sentences, only the name changes)\n")
    for tradition, share in sorted(recall.items(), key=lambda kv: -kv[1]):
        print(f"  {share:6.0%}  {tradition}")
    gap = max(recall.values()) - min(recall.values())
    print(f"\n  Gap between best and worst: {gap:.0%}")
    wrong = false_alarms(detect_names_local)
    print(f"\n  Sentences with no people: {len(NO_PEOPLE)}; wrongly taken for names: {len(wrong)}")
    for sentence, text in wrong:
        print(f"    {text!r} in: {sentence}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
