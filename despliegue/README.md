# Despliegue en frambuesa-yi

Tabularium corre en la Raspberry Pi 5 (`frambuesa-yi`, con un usuario sin privilegios) con tres unidades de systemd de usuario y una del sistema. Nada abre puertos hacia fuera:

| Unidad | Qué hace | Dónde escucha |
|---|---|---|
| `tabularium-diario.timer` y `.service` | Revisa el DOF, baja lo nuevo, reconstruye y glosa, a las 23:15 | No escucha; sale a las fuentes y al gateway de Bakers |
| `tabularium-mcp.service` | Servidor MCP | `127.0.0.1:8061`; `tailscale serve` lo publica solo a la tailnet |
| `tabularium-pagina.service` | Página pública (Novellae y `preguntar`) | `127.0.0.1:8062`, fijo en loopback |
| `cloudflared-tabularium.service` (sistema) | Túnel de Cloudflare: `tabularium.remlam.dev` → `http://127.0.0.1:8062` | Solo conexiones salientes; métricas en `127.0.0.1:20242` |

Por qué systemd y no Docker Compose (la forma estándar de `hosteo`): el servicio es un proceso de Python con `uv` y un archivo de SQLite, ya corría así el timer, y la Pi no tiene Docker. Cada unidad lleva lo que daría el contenedor: sin privilegios nuevos y, en el túnel, un usuario efímero con el sistema en solo lectura. Página y MCP piden `MemoryMax=1500M`, pero el kernel de la Pi arranca con `cgroup_disable=memory` y hoy no se aplica: hace falta `cgroup_enable=memory` en `/boot/firmware/cmdline.txt` y reiniciar (decisión de Bakery). Mientras tanto, la página atiende dos preguntas a la vez y carga el modelo una sola vez.

## Qué hay en la Pi

| Pieza | Dónde |
|---|---|
| uv | `~/.local/share/uv-venv` (instalado con `pip`), enlazado en `~/.local/bin/uv` |
| Repo | `~/tabularium`, clon de GitHub; `uv sync --frozen --no-dev` |
| Caché y base | `~/tabularium/cache` y `~/tabularium/data`. Desde el despliegue, la caché de la Pi es la que avanza cada día |
| Modelo de embeddings | `~/.cache/huggingface` (ya bajado); los servicios corren con `HF_HUB_OFFLINE=1` |
| CLI `baker` | `uv tool install "bakers @ git+https://github.com/RemiH06/Bakery.git#subdirectory=bakers"` (Python 3.13 del sistema); `uv tool upgrade bakers` cuando cambie `bakers.toml` |
| Entorno | `~/.config/tabularium/env`, permisos 600, fuera del repo: `BAKERS_URL`, `BAKERS_API_KEY` y `TABULARIUM_HOSTS` (el nombre de la Pi en la tailnet, para que el MCP acepte ese `Host`) |
| Unidades de usuario | `~/.config/systemd/user/tabularium-*`, copias de esta carpeta |
| `cloudflared` | Paquete del repo de Cloudflare (`/etc/apt/sources.list.d/cloudflared.sources`, llave en `/usr/share/keyrings/cloudflare-main.gpg`), con actualizaciones automáticas (`/etc/apt/apt.conf.d/51unattended-cloudflared`) |
| Token del túnel | `/etc/cloudflared/tabularium.env` (`TUNNEL_TOKEN=...`), de root, permisos 600 |
| Big Chungus (conectado el 2026-11-13, sin montar) | No se usa: su partición es un grupo de almacenamiento de Windows (Storage Spaces), que Linux no lee, y tiene respaldos de Remi. No formatear. Ver `plan.md`, sección 10 |
| Linger | `sudo loginctl enable-linger <usuario>`: las unidades de usuario corren sin sesión abierta |
| IPv4 primero | `/etc/gai.conf`: `precedence ::ffff:0:0/96  100`. El IPv6 de la red de casa no sale a internet y cada petición esperaba 240 s a que fallara |

## Instalar o actualizar

```bash
cd ~/tabularium && git pull && ~/.local/bin/uv sync --frozen --no-dev
cp despliegue/tabularium-*.service despliegue/tabularium-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tabularium-diario.timer tabularium-mcp.service tabularium-pagina.service
systemctl --user restart tabularium-mcp.service tabularium-pagina.service   # si ya corrían
tailscale serve --bg --https=8061 http://127.0.0.1:8061                    # una vez
```

El túnel, una vez (el token lo da el panel de Cloudflare al crear el túnel; es un secreto):

```bash
sudo install -d -m 700 /etc/cloudflared
sudo sh -c 'umask 077; cat > /etc/cloudflared/tabularium.env'   # pegar TUNNEL_TOKEN=... y Ctrl+D
sudo cp despliegue/cloudflared-tabularium.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cloudflared-tabularium.service
```

## Operar

```bash
systemctl --user list-timers                      # próxima corrida del trabajo diario
systemctl --user start tabularium-diario.service  # correr ya
systemctl --user status tabularium-mcp tabularium-pagina
sudo journalctl _SYSTEMD_USER_UNIT=tabularium-pagina.service -o cat --since today   # solo conteos de preguntar
sudo systemctl status cloudflared-tabularium
```

Si Pixilate está apagada, `glosar` falla sin tumbar el trabajo diario, y `preguntar` muestra lo que encontró `buscar` sin respuesta redactada.

## Apagar

```bash
sudo systemctl stop cloudflared-tabularium        # corta lo público; la página y el MCP siguen en la Pi
tailscale serve --https=8061 off                  # saca el MCP de la tailnet
systemctl --user disable --now tabularium-diario.timer
```
