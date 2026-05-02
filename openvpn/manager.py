from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class OpenVPNClient:
    id: str
    name: str
    config: str  # содержимое .ovpn файла


class OpenVPNPoolManager:
    """Менеджер пула готовых .ovpn конфигов для OpenVPN Community Edition.

    Конфиги генерируются заранее на сервере и кладутся в pool_dir.
    Бот берёт следующий свободный файл при каждой активации подписки.
    """

    def __init__(self, pool_dir: str = 'storage/configs/pool') -> None:
        self.pool_dir = Path(pool_dir)
        self.pool_dir.mkdir(parents=True, exist_ok=True)

    def _used_dir(self) -> Path:
        used = self.pool_dir / 'used'
        used.mkdir(parents=True, exist_ok=True)
        return used

    def get_next_config(self) -> OpenVPNClient:
        """Берёт следующий свободный .ovpn файл из пула."""
        ovpn_files = sorted(self.pool_dir.glob('*.ovpn'))
        if not ovpn_files:
            raise RuntimeError(
                'Пул конфигов пуст. Добавьте .ovpn файлы в папку '
                f'{self.pool_dir.resolve()}'
            )

        config_file = ovpn_files[0]
        config_text = config_file.read_text(encoding='utf-8')

        # Перемещаем в used/ чтобы не выдать повторно
        used_path = self._used_dir() / config_file.name
        config_file.rename(used_path)

        client_id = config_file.stem
        return OpenVPNClient(id=client_id, name=client_id, config=config_text)

    def pool_size(self) -> int:
        """Количество свободных конфигов в пуле."""
        return len(list(self.pool_dir.glob('*.ovpn')))
