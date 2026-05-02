from pathlib import Path

import qrcode

from openvpn.manager import OpenVPNClient


def save_config(path: str | Path, config_text: str) -> str:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(config_text, encoding='utf-8')
    return str(file_path)


def generate_qr(path: str | Path, content: str) -> str:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    image = qrcode.make(content)
    image.save(file_path)
    return str(file_path)


def save_client_files(client: OpenVPNClient, base_dir: str = 'storage') -> tuple[str, str]:
    """Сохраняет .ovpn файл и QR-код, возвращает (conf_path, qr_path)."""
    conf_path = save_config(f'{base_dir}/configs/{client.name}.ovpn', client.config)
    qr_path = generate_qr(f'{base_dir}/qr/{client.name}.png', client.config)
    return conf_path, qr_path
