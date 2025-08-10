# Guide d'analyse (lecture seule)

Ce dépôt contient principalement une interface graphique PyQt5 (`assistantGUI.py`). Suivre les étapes ci-dessous pour analyser le projet sans l'exécuter ni le modifier.

1. **Ne pas lancer la GUI** : éviter d'exécuter `assistantGUI.py` durant la revue.
2. **Organisation** : vérifier la séparation entre la logique applicative (`core/`, par ex. `core/logic.py`) et l'interface (`assistant_gui.py`).
3. **Tests** : si le dossier `tests/` est absent, proposer un squelette `pytest` pour `core/logic.py`.
4. **Effets de bord** : confirmer qu'aucun code ne s'exécute à l'import et qu'une CLI existe via `python -m cli`.
5. **Qualité du code** : suggérer l'ajout de `mypy` et `ruff`, et l'amélioration des annotations de type et docstrings.
6. **Dépendances** : si elles manquent, proposer un `requirements.txt` minimal listant les bibliothèques nécessaires.
7. **Intégration continue** : si aucune CI n'est présente, recommander un workflow GitHub Actions minimal (installation, `ruff`, `mypy`, `pytest`).

