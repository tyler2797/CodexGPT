# CodexGPT

## Introduction
Un outil minimal combinant une CLI et une interface graphique pour expérimenter l'assistant.

## Prérequis
- Python >= 3.10

## Installation
```bash
pip install -r requirements.txt
```
ou si un `pyproject.toml` est présent :
```bash
pip install .
```

## Exécution
CLI :
```bash
python -m cli "hello world"
```
GUI :
```bash
python assistantGUI.py
```

## Tests
```bash
pytest
```

## Qualité
```bash
ruff check .
mypy .
```

## Structure du projet
```text
.
├── assistantGUI.py
└── README.md
```

## Licence
MIT

