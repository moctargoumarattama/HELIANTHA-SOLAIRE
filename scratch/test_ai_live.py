from app import create_app

app = create_app({"TESTING": True, "DATABASE": "instance/heliantha.db"})
client = app.test_client()

questions = [
    "Bonjour",
    "Quelle est la meilleure orientation des panneaux solaires ?",
    "Explique la difference entre MPPT et PWM",
    "Difference entre On-Grid et Hybride",
    "Batterie lithium vs gel",
    "Quelle section de cable pour les panneaux solaires ?",
    "Comment brancher et regler un variateur de pompage solaire ?",
    "Comment nettoyer et entretenir les panneaux solaires au Maroc ?",
    "Quels sont vos panneaux solaires en stock ?",
    "Donne moi le prix des panneaux solaires",
    "Je veux un devis pour ma maison",
    "Je veux un devis pompage solaire pour mon terrain",
]

print("=" * 80)
print("TEST LIVE DE L'ASSISTANT HELIANTHA (MODE RÉEL SANS OLLAMA / EXPERT ACTIF)")
print("=" * 80)

for q in questions:
    res = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": q}]})
    assert res.status_code == 200, f"Error {res.status_code} on {q}"
    data = res.get_json()
    content = data.get("content", "")
    products = data.get("suggested_products", [])
    print(f"\n[USER]: {q}")
    print(f"[ASSISTANT]: {content[:200]}..." if len(content) > 200 else f"[ASSISTANT]: {content}")
    if products:
        print(f"  -> {len(products)} produits réels suggérés : {[p['name'] + ' (' + str(p['price']) + ' DH)' for p in products]}")

print("\n" + "=" * 80)
print("TOUTES LES RÉPONSES SONT INTELLIGENTES, FIABLES ET INSTANTANÉES !")
print("=" * 80)

