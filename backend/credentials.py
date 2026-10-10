"""Shared encrypted credential vault; secrets never belong in task snapshots."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from backend.contracts import DomainError, require


def credential_environment(environ=None):
    if environ is not None:
        return dict(environ)
    from backend.provider import ROOT
    values={}
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                values[key.strip()]=value.strip().strip('\"\'')
    values.update(os.environ)
    return values


class CredentialVault:
    def __init__(self,store,environ=None):
        self.store,self.environ=store,credential_environment(environ)

    def _cipher(self):
        from cryptography.fernet import Fernet
        from backend.provider import ROOT
        key=self.environ.get('MODEL_CREDENTIAL_KEY','').strip()
        if not key:
            host=urlsplit(self.environ.get('PUBLIC_ORIGIN','http://127.0.0.1')).hostname
            require(host in ('127.0.0.1','localhost','::1'),'CONFIG_INVALID','公网部署必须配置 MODEL_CREDENTIAL_KEY 加密主密钥')
            folder=ROOT/'runtime' if self.store.postgres else Path(self.store.path).resolve().parent
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/'credentials.key'
            if not path.exists():
                import tempfile
                fd,temporary=tempfile.mkstemp(prefix='.credentials-',dir=folder)
                try:
                    with os.fdopen(fd,'wb') as output:
                        output.write(Fernet.generate_key());output.flush();os.fsync(output.fileno())
                    try:os.link(temporary,path)
                    except FileExistsError:pass
                finally:os.unlink(temporary)
            require(not path.is_symlink() and path.is_file() and path.stat().st_mode & 0o077==0,'CONFIG_INVALID','本地密钥文件必须是权限 0600 的普通文件')
            key=path.read_bytes()
        try:return Fernet(key)
        except (ValueError,TypeError):raise DomainError('CONFIG_INVALID','MODEL_CREDENTIAL_KEY 格式无效；需要 Fernet 主密钥') from None

    def encrypt(self,value):
        return self._cipher().encrypt(value.encode()).decode()

    def decrypt(self,value):
        from cryptography.fernet import InvalidToken
        try:return self._cipher().decrypt(value.encode()).decode()
        except (InvalidToken,UnicodeError):raise DomainError('CONFIG_INVALID','凭证无法解密，请恢复原主密钥或重新保存连接') from None
