# Port, DNS name and HTTPS

All networking is set with `./deploy.sh` options. They are saved in `.env`, so later runs (`./deploy.sh` with no
options) keep them. If a run fails, nothing is saved. Your data is never affected by any of these changes.

At the end of every run `deploy.sh` prints the address to open.

---

## 1. Change the port (e.g. 8080 is already taken)

```bash
./deploy.sh --port 9090
```

Users open `http://<server-ip>:9090`. Before starting, `deploy.sh` checks the port. If another program is using it,
the script stops and suggests the next free port. Nothing is changed in that case.

## 2. Use the DNS name you were given

First make sure the DNS name points to the server: an **A record** with the server's IP address, set by whoever
manages your DNS. You can check with `nslookup hackeduler.example.com`.

**Plain HTTP, no certificate:**

```bash
./deploy.sh --domain hackeduler.example.com --port 80     # users open http://hackeduler.example.com
./deploy.sh --domain hackeduler.example.com --port 9090   # users open http://hackeduler.example.com:9090
```

Setting the domain also updates the links in emails and the SSO redirect address.

## 3. DNS name with HTTPS (recommended)

Hackeduler includes an HTTPS front end (Caddy) that handles certificates. Pick one mode:

| Mode | Use when | Command |
|---|---|---|
| `files` | Your company gives you a certificate for the DNS name (typical for internal names) | Copy the certificate to `certs/fullchain.pem` and the key to `certs/privkey.pem`, then `./deploy.sh --domain hackeduler.example.com --https files` |
| `auto` | The server is reachable **from the internet** on ports 80 and 443 | `./deploy.sh --domain hackeduler.example.com --https auto --email you@example.com` (free Let's Encrypt certificate, renewed automatically) |
| `internal` | Testing only | `./deploy.sh --domain hackeduler.example.com --https internal` (self-signed: browsers show a warning) |

Users open `https://hackeduler.example.com`, and plain `http://` is redirected to HTTPS. If 443 or 80 are taken:

```bash
./deploy.sh --https-port 8443 --http-port 8081     # users open https://hackeduler.example.com:8443
```

To allow **only** HTTPS, so the plain port can't be reached from other machines, add `--bind 127.0.0.1`.

Turn HTTPS off again with `./deploy.sh --https off`. Remove the DNS name with `./deploy.sh --domain ""`.

When the certificate is renewed (mode `files`), copy the new files into `certs/` and run
`docker compose restart https`.

> If SSO is configured, check **Admin → Single Sign-On → Public application URL**. Leave it empty to follow the
> settings above, or set it to the new address, and update the redirect URI registered at your identity provider.

## 4. The server already has a web server (nginx, Apache, IIS) on 80/443

Keep using it, and let it forward the DNS name to Hackeduler on a local port:

```bash
./deploy.sh --port 8090 --bind 127.0.0.1 --domain hackeduler.example.com
```

Then add a site to the existing web server.

**nginx**

```nginx
server {
    listen 443 ssl;
    server_name hackeduler.example.com;
    ssl_certificate     /etc/ssl/hackeduler/fullchain.pem;
    ssl_certificate_key /etc/ssl/hackeduler/privkey.pem;
    client_max_body_size 3m;
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

**Apache** (`mod_proxy`, `mod_proxy_http`, `mod_headers`)

```apache
<VirtualHost *:443>
    ServerName hackeduler.example.com
    SSLEngine on
    SSLCertificateFile    /etc/ssl/hackeduler/fullchain.pem
    SSLCertificateKeyFile /etc/ssl/hackeduler/privkey.pem
    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass        / http://127.0.0.1:8090/
    ProxyPassReverse / http://127.0.0.1:8090/
</VirtualHost>
```

**IIS**: install *URL Rewrite* and *Application Request Routing*, create a site bound to the DNS name with your
certificate, and add a reverse-proxy rule to `http://127.0.0.1:8090`.

If that proxy serves HTTPS, set `HACKEDULER_APP_BASE_URL=https://hackeduler.example.com` and
`HACKEDULER_COOKIE_SECURE=true` in `.env`, and run `./deploy.sh` once. (`deploy.sh` can't see an external proxy, so it
assumes plain HTTP for `--domain` without `--https`.)

---

## Reference: `.env` settings

| Setting | Meaning | Default |
|---|---|---|
| `HACKEDULER_HTTP_PORT` | Port the app is served on | `8080` |
| `HACKEDULER_BIND_ADDRESS` | `0.0.0.0` all networks, `127.0.0.1` this server only | `0.0.0.0` |
| `HACKEDULER_DOMAIN` | DNS name | empty |
| `HACKEDULER_HTTPS` | `off`, `files`, `auto`, `internal` | `off` |
| `HACKEDULER_HTTPS_PORT` / `HACKEDULER_HTTP_REDIRECT_PORT` | HTTPS port / HTTP→HTTPS redirect port | `443` / `80` |
| `HACKEDULER_ACME_EMAIL` | Contact email for Let's Encrypt (`auto`) | empty |

`HACKEDULER_APP_BASE_URL`, `HACKEDULER_COOKIE_SECURE`, `HACKEDULER_CADDY_TLS`, `HACKEDULER_HTTPS_PORT_SUFFIX` and
`COMPOSE_PROFILES` are worked out by `deploy.sh` from the settings above, so you don't need to edit them.

## Using a DNS name as well as the IP address (ERR_SSL_PROTOCOL_ERROR)

The built-in HTTPS front serves its certificate and the application to any name that reaches it (`default_sni`,
`fallback_sni` and the catch-all `https://` block in `deploy/Caddyfile`), so `https://<ip>:PORT` and `https://<dns-name>:PORT` both complete the TLS handshake. If the
certificate does not list the name you type, the browser shows a certificate-name warning (fix: use a certificate
whose SAN includes that name). Two more things to align when you start using a different name:

* the Microsoft Entra app registration needs the new `https://<name>:PORT/api/auth/sso/callback` redirect URI, and
  `HACKEDULER_BASE_URL` decides which address SSO returns users to;
* sessions are per address - signing in on the IP does not sign you in on the DNS name.
