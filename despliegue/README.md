# Despliegue en frambuesa-yi

El trabajo diario corre en la Raspberry Pi 5 (`frambuesa-yi`, usuario `sherry`) como unidad de systemd de usuario. No abre puertos: solo sale a las fuentes y al gateway de Bakers en la tailnet.

## Qué hay en la Pi

| Pieza | Dónde |
|---|---|
| uv | `~/.local/share/uv-venv` (instalado con `pip`), enlazado en `~/.local/bin/uv` |
| Repo | `~/tabularium`, clon de GitHub; `uv sync --frozen --no-dev` |
| Caché y base | `~/tabularium/cache` y `~/tabularium/data`. Desde el despliegue, la caché de la Pi es la que avanza cada día |
| Modelo de embeddings | `~/.cache/huggingface` (ya bajado); el servicio corre con `HF_HUB_OFFLINE=1` |
| CLI `baker` | `uv tool install "bakers @ git+https://github.com/RemiH06/Bakery.git#subdirectory=bakers"` (Python 3.13 del sistema) |
| Credenciales del gateway | `~/.config/tabularium/env` (`BAKERS_URL`, `BAKERS_API_KEY`), permisos 600, fuera del repo |
| Unidades | `~/.config/systemd/user/tabularium-diario.{service,timer}`, copias de esta carpeta |
| Linger | `sudo loginctl enable-linger sherry`: el timer corre sin sesión abierta |
| IPv4 primero | `/etc/gai.conf`: `precedence ::ffff:0:0/96  100`. El IPv6 de la red de casa no sale a internet y cada petición esperaba 240 s a que fallara |

## Instalar o actualizar

```bash
cd ~/tabularium && git pull && ~/.local/bin/uv sync --frozen --no-dev
cp despliegue/tabularium-diario.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tabularium-diario.timer
```

## Operar

```bash
systemctl --user list-timers                      # próxima corrida
systemctl --user start tabularium-diario.service  # correr ya
sudo journalctl _SYSTEMD_USER_UNIT=tabularium-diario.service -o cat --since today
systemctl --user disable --now tabularium-diario.timer  # apagar
```

Si Pixilate está apagada, `glosar` falla sin tumbar el servicio y las glosas se piden en la siguiente corrida.
