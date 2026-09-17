"""Sous-commande `ourouler geocoder` : adresse tapée -> candidats notés.

Ce sous-paquet est du cœur : il ne lit ni fichier de configuration, ni
variable d'environnement. Il reçoit les clients HTTP du connecteur
(`ourouler.connecteurs.geocodage`), injectables pour les tests.
"""
