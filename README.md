# KAREN

Asistente de voz y automatización personal, con arquitectura modular por responsabilidades.

## Objetivo

KAREN combina:
- escucha por micrófono
- procesamiento del lenguaje
- control de voz con síntesis
- automatización del PC
- luces, monitoreo web y HUD local

La idea es que cada parte viva en su propio archivo y carpeta, y no se mezcle toda la lógica en un único script.

## Estructura del proyecto

```text
jarvis/
├─ main.py                  # punto de entrada principal
├─ config.py                # ajustes y claves de configuración
├─ requirements.txt         # dependencias de Python
├─ README.md                # documentación del proyecto
├─ .gitignore               # archivos sensibles y temporales
├─ acciones/
│  ├─ __init__.py           # coordinador de acciones
│  ├─ luces.py              # control de luces LED
│  ├─ pc.py                 # control de apps / acceso PC
│  ├─ pc_extra.py           # utilidades extra del PC
│  └─ webmon.py             # monitorización de sitios web
├─ core/
│  ├─ __init__.py
│  ├─ boca.py               # síntesis de voz
│  ├─ cerebro.py            # lógica del asistente / decisiones
│  ├─ emociones.py          # estado emocional
│  ├─ eventos.py            # bus de eventos interno
│  ├─ llm_router.py         # router de modelos LLM
│  ├─ memoria.py            # memoria local
│  ├─ mundo.py              # clima, noticias, resumen del día
│  ├─ oido.py               # micrófono + STT + wake word
│  └─ vozprint.py           # voz / perfiles de usuario
├─ web/
│  ├─ __init__.py
│  └─ servidor.py           # API FastAPI + HUD embebido
├─ secrets.json.example     # ejemplo de configuración sensible
└─ ...
```

## Cómo se ejecuta

```bash
python main.py
```

## Reglas para GitHub

- No subir secretos reales.
- Guardar claves en `secrets.json` localmente y no versionarlas.
- Mantener la lógica separada por carpeta y responsable.

## Configuración

1. Copia `secrets.json.example` a `secrets.json`.
2. Completa tus claves si las necesitas.
3. Instala dependencias:

```bash
pip install -r requirements.txt
```

## Recomendación para subir a GitHub

```bash
git init
git add .
git commit -m "Primer commit: KAREN modular"
git branch -M main
git remote add origin https://github.com/tu-usuario/tu-repo.git
git push -u origin main
```

## Nota

Este proyecto ya está dividido por módulos y responsabilidades; la separación principal es:
- `core/` para inteligencia y flujo interno
- `acciones/` para comandos del sistema
- `web/` para interfaz HTTP/HUD
- `main.py` como entrada principal
- `config.py` para ajustes globales
