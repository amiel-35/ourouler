"""Preuve que la garde réseau de `tests/conftest.py` couvre toute la suite.

`reseau_interdit` (autouse, racine) est déjà actif pour ce module comme pour
tous les autres : pas besoin de l'invoquer explicitement, juste de vérifier
qu'il mord. `192.0.2.1` est une adresse documentaire (TEST-NET-1, RFC 5737) :
jamais routée, donc jamais un vrai faux positif si la garde avait un trou.

La classe `ReseauInterdit` est reçue par la fixture `classe_reseau_interdit`
plutôt qu'importée par `from conftest import ...` : quatre `conftest.py`
coexistent sous `tests/`, tous nommés `conftest` une fois chargés, et cet
import résoudrait au hasard de l'ordre de collecte (voir le docstring de la
fixture dans `tests/conftest.py`).
"""

from __future__ import annotations

import socket

import pytest

# TEST-NET-1 (RFC 5737) : réservée à la documentation, jamais assignée.
HOTE_PUBLIC_DOC = "192.0.2.1"
PORT_QUELCONQUE = 80


def test_connect_vers_une_adresse_publique_est_refuse(classe_reseau_interdit):
    with pytest.raises(classe_reseau_interdit, match=r"192\.0\.2\.1:80"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOTE_PUBLIC_DOC, PORT_QUELCONQUE))


def test_create_connection_vers_une_adresse_publique_est_refuse(classe_reseau_interdit):
    with pytest.raises(classe_reseau_interdit, match=r"192\.0\.2\.1:80"):
        socket.create_connection((HOTE_PUBLIC_DOC, PORT_QUELCONQUE), timeout=1)


def test_getaddrinfo_vers_un_hote_public_est_refuse(classe_reseau_interdit):
    with pytest.raises(classe_reseau_interdit):
        socket.getaddrinfo("exemple.invalide", PORT_QUELCONQUE)


def test_connect_vers_127_0_0_1_n_est_pas_bloque_par_la_garde(classe_reseau_interdit):
    """La boucle locale reste ouverte : `tests/comptes/` en a besoin.

    Rien n'écoute forcément sur ce port ici : un refus de connexion du
    système d'exploitation est attendu et accepté. Seule `ReseauInterdit`,
    signe que *la garde* a bloqué l'appel, est un échec du test.
    """
    with pytest.raises(OSError) as exc_info:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", 1))
    assert not isinstance(exc_info.value, classe_reseau_interdit)


def test_connect_vers_localhost_n_est_pas_bloque_par_la_garde(classe_reseau_interdit):
    with pytest.raises(OSError) as exc_info:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("localhost", 1))
    assert not isinstance(exc_info.value, classe_reseau_interdit)
