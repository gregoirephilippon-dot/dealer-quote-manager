"""Account recovery endpoints, registered against the existing FastAPI application."""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import server_user_model as users
from password_security import hash_password

LOG = logging.getLogger(__name__)

def utcnow():
    return datetime.now(timezone.utc)

def init_tokens():
    with users.get_connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS account_recovery_tokens (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          kind TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS ix_recovery_user ON account_recovery_tokens(user_id, kind, created_at)')
        db.commit()

def digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

# DQM_AUTH_TRUSTED_ORIGIN_V1
# N'utiliser jamais Host/X-Forwarded-Host pour un lien envoye par e-mail.
def _trusted_link_origin(untrusted_base_url):
    from urllib.parse import urlsplit
    import app_config
    mode=os.getenv('DQM_AUTH_MAIL_MODE','dry-run').strip().lower()
    if mode not in ('dry-run','smtp'):
        raise RuntimeError('DQM_AUTH_MAIL_MODE invalide')
    if mode == 'smtp':
        configured=os.getenv('DQM_AUTH_PUBLIC_URL','').strip()
        parsed=urlsplit(configured)
        if (parsed.scheme!='https' or parsed.hostname!='dealerquotemanager.com'
                or parsed.username or parsed.password or parsed.port not in (None,443)
                or parsed.path not in ('','/') or parsed.query or parsed.fragment):
            raise RuntimeError('DQM_AUTH_PUBLIC_URL doit etre https://dealerquotemanager.com')
        return 'https://dealerquotemanager.com'
    if str(app_config.APP_ENV).lower() not in ('local','dev','development','test'):
        raise RuntimeError('Mode simulation interdit hors environnement local')
    p=urlsplit(untrusted_base_url)
    if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost') or p.username or p.password:
        raise RuntimeError('Lien local : hote non autorise')
    return p.scheme+'://'+p.netloc

def issue(user, kind, base_url):
    if kind not in ('reset','invite'):
        raise ValueError('Type de lien inconnu')
    base_url=_trusted_link_origin(base_url)
    init_tokens()
    moment=utcnow()
    uid=int(user['id'])
    with users.get_connection() as db:
        previous=db.execute('SELECT created_at FROM account_recovery_tokens WHERE user_id=? AND kind=? ORDER BY id DESC LIMIT 1',(uid,kind)).fetchone()
        if previous and (moment-datetime.fromisoformat(previous['created_at'])).total_seconds()<90:
            return False
        token=secrets.token_urlsafe(32)
        db.execute('UPDATE account_recovery_tokens SET used_at=? WHERE user_id=? AND kind=? AND used_at IS NULL',(moment.isoformat(),uid,kind))
        db.execute('INSERT INTO account_recovery_tokens(user_id,kind,token_hash,created_at,expires_at) VALUES (?,?,?,?,?)',
                   (uid,kind,digest(token),moment.isoformat(),(moment+timedelta(minutes=30)).isoformat()))
        db.commit()
    path='/activate-account' if kind=='invite' else '/reset-password'
    url=base_url.rstrip('/')+path+'?token='+token
    try:
        send_email(user['email'],kind,url)
    except Exception:
        with users.get_connection() as db:
            db.execute('UPDATE account_recovery_tokens SET used_at=? WHERE token_hash=?',(utcnow().isoformat(),digest(token)))
            db.commit()
        raise
    return True

def send_email(destination, kind, link):
    # DQM_LOCAL_AUTH_OUTBOX_V1 - essais locaux sans SMTP et sans jeton dans les logs.
    import app_config
    from urllib.parse import urlsplit
    mode = os.getenv('DQM_AUTH_MAIL_MODE', 'dry-run').strip().lower()
    _trusted_link_origin(link.split('/reset-password?', 1)[0].split('/activate-account?', 1)[0])
    if mode != 'smtp':
        # Ne jamais ecrire de liens secrets sur le disque d'un serveur public.
        host = (urlsplit(link).hostname or '').lower()
        if str(app_config.APP_ENV).lower() not in ('local', 'dev', 'development', 'test') or host not in ('localhost', '127.0.0.1'):
            raise RuntimeError('Boite de test interdite hors environnement local et URL localhost')
        from pathlib import Path
        directory = Path(app_config.BASE_DIR) / 'data' / 'auth_test_outbox'
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        marker = secrets.token_hex(8)
        filename = directory / ('message_' + marker + '.txt')
        body = ('DESTINATAIRE: ' + destination + '\n'
                + 'TYPE: ' + kind + '\n'
                + 'LIEN_TEST_LOCAL: ' + link + '\n')
        with open(filename, 'x', encoding='utf-8') as output:
            output.write(body)
        try:
            os.chmod(filename, 0o600)
        except OSError:
            pass
        return
    from contract_delivery_processor import _send_email_smtp, _smtp_settings
    message=EmailMessage()
    message['From']=_smtp_settings()['user']
    message['To']=destination
    message['Subject']='Invitation Dealer Quote Manager' if kind=='invite' else 'Reinitialisation Dealer Quote Manager'
    message.set_content('Pour choisir votre mot de passe, ouvrez ce lien valable 30 minutes :\n\n'+link+'\n\nSi vous n\'avez rien demande, ignorez cet e-mail.')
    _send_email_smtp(message)

def find_token(token,kind):
    if not token or len(token)>200 or kind not in ('reset','invite'):
        return None
    init_tokens()
    with users.get_connection() as db:
        row=db.execute('''SELECT t.*,u.email,u.status FROM account_recovery_tokens t
        JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.kind=?''',(digest(token),kind)).fetchone()
    if not row or row['used_at'] or datetime.fromisoformat(row['expires_at'])<=utcnow():
        return None
    if row['status']!='active' or not users.user_has_active_company_access(row['email']):
        return None
    return row

def redeem(token,kind,password):
    if not 12<=len(password)<=256:
        raise ValueError('12 caractères minimum et 256 maximum')
    row=find_token(token,kind)
    if row is None:return False
    stamp=utcnow().isoformat()
    secure_hash=hash_password(password)
    with users.get_connection() as db:
        result=db.execute('UPDATE account_recovery_tokens SET used_at=? WHERE id=? AND used_at IS NULL AND expires_at>?',(stamp,row['id'],stamp))
        if result.rowcount!=1:return False
        db.execute('UPDATE users SET password_hash=?,updated_at=? WHERE id=?',(secure_hash,stamp,row['user_id']))
        db.execute('UPDATE account_recovery_tokens SET used_at=? WHERE user_id=? AND used_at IS NULL',(stamp,row['user_id']))
        db.commit()
    return True

def page(title,inside):
    return HTMLResponse(f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
    <style>body{{font-family:Arial,sans-serif;background:#eaf0f7;margin:0;padding:24px}}main{{max-width:470px;background:white;margin:7vh auto;padding:30px;border-radius:14px;box-shadow:0 12px 32px #10325e22}}
    label,input,button{{display:block;width:100%;box-sizing:border-box}}input{{padding:12px;margin:8px 0 20px;border:1px solid #ccd5e5;border-radius:8px}}button{{padding:13px;background:#0756c8;color:#fff;border:0;border-radius:8px;cursor:pointer}}a{{color:#0756c8}}</style></head>
    <body><main><h1>{escape(title)}</h1>{inside}<p><a href="/login">Retour à la connexion</a></p></main></body></html>''')

def register(app, require_admin):
    @app.get('/forgot-password')
    def forgot_page():
        return page('Mot de passe oublié ?', '<form method="post"><label>Votre adresse e-mail<input type="email" name="email" required autocomplete="email"></label><button>Recevoir un lien</button></form>')

    @app.post('/forgot-password')
    def forgot_post(request: Request, email: str=Form('')):
        try:
            email=email.strip().lower()
            user=users.get_user_by_email(email)
            if user and user['status']=='active' and users.user_has_active_company_access(email):
                issue(user,'reset',str(request.base_url))
        except Exception:
            LOG.exception('Récupération : impossible de traiter la demande')
        return page('Vérifiez vos e-mails','<p>Si cette adresse dispose d’un compte actif, un lien sera envoyé.</p>')

    @app.get('/reset-password')
    @app.get('/activate-account')
    def form_page(request: Request, token: str=''):
        kind='invite' if request.url.path=='/activate-account' else 'reset'
        if not find_token(token,kind):
            return page('Lien indisponible','<p>Le lien est expiré, déjà utilisé ou le compte n’est pas actif.</p>')
        action=request.url.path
        return page('Définir votre mot de passe',f'''<form method="post" action="{action}"><input type="hidden" name="token" value="{escape(token,quote=True)}">
        <label>Nouveau mot de passe<input name="password" type="password" minlength="12" required autocomplete="new-password"></label>
        <label>Confirmer<input name="confirmation" type="password" minlength="12" required autocomplete="new-password"></label>
        <button>Enregistrer</button></form>''')

    @app.post('/reset-password')
    @app.post('/activate-account')
    def form_post(request: Request, token: str=Form(''), password: str=Form(''), confirmation: str=Form('')):
        if password != confirmation:return page('Erreur','<p>Les mots de passe ne correspondent pas. Réouvrez le lien et recommencez.</p>')
        kind='invite' if request.url.path=='/activate-account' else 'reset'
        try:ok=redeem(token,kind,password)
        except ValueError:return page('Erreur','<p>Le mot de passe doit contenir au moins 12 caractères.</p>')
        return page('Mot de passe enregistré' if ok else 'Lien indisponible','<p>Vous pouvez vous connecter.</p>' if ok else '<p>Le lien a expiré ou a déjà été utilisé.</p>')

    @app.post('/server/users/{user_id}/invite')
    def resend_invite(user_id:int, request:Request):
        rejected=require_admin(request)
        if rejected:return rejected
        with users.get_connection() as db:
            user=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or user['status']!='active' or not users.user_has_active_company_access(user['email']):
            return HTMLResponse('Compte ou accès société inactif.',status_code=400)
        try:issue(user,'invite',str(request.base_url))
        except Exception:
            LOG.exception('Invitation SMTP échouée')
            return HTMLResponse('Invitation non envoyée. Vérifiez SMTP et réessayez.',status_code=503)
        return RedirectResponse('/server/users',status_code=303)
