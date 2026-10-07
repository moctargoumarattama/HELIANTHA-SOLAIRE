from app import create_app
from app.db import get_user, list_users, save_user


def test_admin_users_page_and_listing(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-users.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    page = client.get("/admin/utilisateurs")
    assert page.status_code == 200
    assert b"Gestion des Utilisateurs" in page.data
    assert b"direction@heliantha.ma" in page.data
    assert b"Direction" in page.data


def test_admin_users_create_commercial_and_direction(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-users-create.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    # Création d'un commercial
    res_comm = client.post(
        "/admin/utilisateurs",
        data={
            "action": "save",
            "email": "karim@heliantha.ma",
            "display_name": "Karim Alami",
            "role": "Commercial",
            "password": "SecretPassword123",
        },
        follow_redirects=True,
    )
    assert res_comm.status_code == 200
    assert b"karim@heliantha.ma" in res_comm.data
    assert b"Karim Alami" in res_comm.data

    with app.app_context():
        users = list_users()
        karim = next((u for u in users if u["username"] == "karim@heliantha.ma"), None)
        assert karim is not None
        assert karim["role"] == "Commercial"
        assert karim["display_name"] == "Karim Alami"

    # Création d'un second administrateur Direction
    res_dir = client.post(
        "/admin/utilisateurs",
        data={
            "action": "save",
            "email": "direction2@heliantha.ma",
            "display_name": "Direction Adjointe",
            "role": "Direction",
            "password": "AdminPassword123",
        },
        follow_redirects=True,
    )
    assert res_dir.status_code == 200

    with app.app_context():
        users = list_users()
        dir2 = next((u for u in users if u["username"] == "direction2@heliantha.ma"), None)
        assert dir2 is not None
        assert dir2["role"] == "Direction"


def test_admin_users_edit_account(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-users-edit.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    with app.app_context():
        uid = save_user(
            username="vendeur@heliantha.ma",
            display_name="Vendeur Initial",
            role="Commercial",
            password="pwd",
        )

    # Modification sans changer le mot de passe
    res_edit = client.post(
        "/admin/utilisateurs",
        data={
            "action": "save",
            "user_id": str(uid),
            "email": "vendeur.pro@heliantha.ma",
            "display_name": "Vendeur Senior",
            "role": "Commercial",
            "password": "",  # laisser vide
        },
        follow_redirects=True,
    )
    assert res_edit.status_code == 200

    with app.app_context():
        updated = get_user(uid)
        assert updated["username"] == "vendeur.pro@heliantha.ma"
        assert updated["display_name"] == "Vendeur Senior"


def test_admin_users_delete_guardrails(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test-users-del.db")})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "direction@heliantha.ma"

    with app.app_context():
        users = list_users()
        current_admin = next(u for u in users if u["username"] == "direction@heliantha.ma")
        comm_id = save_user(
            username="temp@heliantha.ma",
            display_name="Temp User",
            role="Commercial",
            password="pwd",
        )

    # 1. Tentative de suppression du compte connecté -> Bloqué
    res_self = client.post(
        "/admin/utilisateurs",
        data={"action": "delete", "user_id": str(current_admin["id"])},
    )
    assert "Vous ne pouvez pas supprimer le compte actuellement connect" in res_self.data.decode("utf-8")

    # 2. Suppression d'un compte commercial -> Autorisé
    res_del_comm = client.post(
        "/admin/utilisateurs",
        data={"action": "delete", "user_id": str(comm_id)},
        follow_redirects=True,
    )
    assert res_del_comm.status_code == 200
    with app.app_context():
        assert get_user(comm_id) is None
