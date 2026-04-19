# SMC Monitor — lib_version_check.py
# Versão: 0.1.4

"""
OBJETIVO: Consultar PyPI semanalmente para detectar novas versões da
          smartmoneyconcepts e alertar via Telegram quando houver.
          Expõe get_lib_version() como fonte canônica de versão instalada.
FONTE DE DADOS: https://pypi.org/pypi/smartmoneyconcepts/json
LIMITAÇÕES CONHECIDAS: depende de acesso à internet, depende do PyPI
                       estar online. Falhas silenciosas — nunca derrubam
                       o daemon.
NÃO FAZER: não fazer upgrade automático, não bloquear o daemon em caso
           de falha de rede.
"""

import logging

import requests

import telegram

logger = logging.getLogger(__name__)

VERSION = "0.1.5"

PYPI_URL = "https://pypi.org/pypi/smartmoneyconcepts/json"


def get_lib_version() -> str | None:
    """
    OBJETIVO
    --------
    Retornar a versão instalada da biblioteca smartmoneyconcepts de
    forma canônica, única fonte de verdade para toda detecção de
    versão no projeto. Substitui implementações locais dispersas.

    FONTE DE DADOS
    --------------
    importlib.metadata.version("smartmoneyconcepts") como via primária.
    Fallback para atributo __version__ do módulo se metadata falhar.

    LIMITAÇÕES CONHECIDAS
    ---------------------
    Retorna None se a lib não estiver instalada ou se ambos os
    métodos de detecção falharem. Chamador deve tratar None.

    NÃO FAZER
    ---------
    - Não fazer import condicional da lib só para pegar versão
    - Não cachear resultado (a lib pode ser reinstalada em runtime
      em cenários de manutenção)
    """
    try:
        from importlib.metadata import version
        return version("smartmoneyconcepts")
    except Exception:
        pass
    try:
        import smartmoneyconcepts
        return getattr(smartmoneyconcepts, "__version__", None)
    except Exception:
        return None


def check_for_updates() -> None:
    """
    OBJETIVO: consultar PyPI e comparar versão instalada com a última publicada.
              Se houver versão nova, enviar alerta Telegram.
    FONTE DE DADOS: PYPI_URL e get_lib_version().
    LIMITAÇÕES CONHECIDAS: qualquer erro é logado como warning e nunca propaga.
    NÃO FAZER: não fazer upgrade automático, não abortar o daemon em caso de erro.
    """
    try:
        installed = get_lib_version()

        resp = requests.get(PYPI_URL, timeout=10)
        resp.raise_for_status()
        latest = resp.json()["info"]["version"]

        if installed != latest:
            msg = (
                f"📦 smartmoneyconcepts — nova versão disponível\n\n"
                f"Instalada: {installed}\n"
                f"Última no PyPI: {latest}\n\n"
                f"AÇÃO RECOMENDADA:\n"
                f"1. Revisar changelog em:\n"
                f"   https://github.com/joshyattridge/smart-money-concepts/releases\n"
                f"2. Rodar tools/validate_engine.py contra a nova versão\n"
                f"3. Atualizar requirements.txt após validação\n\n"
                f"Sistema continua rodando na versão {installed}."
            )
            telegram.send_signal(msg)
            logger.info("Library update available: %s -> %s", installed, latest)
        else:
            logger.debug("Library up to date: %s", installed)

    except requests.RequestException as e:
        logger.warning("PyPI check failed (network): %s", e)
    except (KeyError, ValueError) as e:
        logger.warning("PyPI check failed (parse): %s", e)
    except Exception as e:
        logger.warning("PyPI check failed (unexpected): %s", e)
