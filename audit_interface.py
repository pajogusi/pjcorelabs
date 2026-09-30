from pathlib import Path
import re
import sys

print("\n=== BLESSED MULTIUSER — AUDITORIA DE INTERFACE ===\n")

# ---------------------------------------------------------
# 1. Compilar/importar aplicação
# ---------------------------------------------------------
try:
    import app as blessed
    app = blessed.app
    print("✅ app.py importado corretamente")
except Exception as e:
    print(f"❌ ERRO ao importar app.py: {e}")
    sys.exit(1)

# ---------------------------------------------------------
# 2. Rotas Flask
# ---------------------------------------------------------
rotas = set()

for rule in app.url_map.iter_rules():
    rotas.add(rule.rule)

print(f"✅ {len(rotas)} rotas Flask encontradas")

# rotas sem parâmetros para teste GET
rotas_get = []

for rule in app.url_map.iter_rules():
    if "GET" in rule.methods and "<" not in rule.rule:
        rotas_get.append(rule.rule)

# ---------------------------------------------------------
# 3. Templates
# ---------------------------------------------------------
templates_dir = Path("templates")

if not templates_dir.exists():
    print("❌ Pasta templates não encontrada")
    sys.exit(1)

templates = list(templates_dir.glob("*.html"))

print(f"✅ {len(templates)} templates encontrados")

problemas = []
avisos = []

# ---------------------------------------------------------
# 4. Verificar links e forms
# ---------------------------------------------------------
for ficheiro in templates:
    texto = ficheiro.read_text(errors="ignore")

    # href estáticos
    hrefs = re.findall(
        r'href=["\']([^"\']+)["\']',
        texto,
        flags=re.I
    )

    for href in hrefs:

        if (
            href.startswith("http://")
            or href.startswith("https://")
            or href.startswith("mailto:")
            or href.startswith("tel:")
            or href.startswith("#")
            or "{{" in href
        ):
            continue

        caminho = href.split("?")[0]

        if caminho.startswith("/") and caminho not in rotas:
            # aceitar rotas dinâmicas construídas diretamente
            existe_dinamica = False

            for rota in rotas:
                base = rota.split("<")[0]

                if "<" in rota and caminho.startswith(base):
                    existe_dinamica = True
                    break

            if not existe_dinamica:
                problemas.append(
                    f"{ficheiro.name}: link sem rota -> {href}"
                )

    # forms
    actions = re.findall(
        r'<form[^>]+action=["\']([^"\']+)["\']',
        texto,
        flags=re.I
    )

    for action in actions:

        if "{{" in action:
            # rota dinâmica — verificamos apenas prefixo
            prefixo = action.split("{{")[0]

            encontrado = any(
                rota.startswith(prefixo)
                for rota in rotas
            )

            if not encontrado:
                problemas.append(
                    f"{ficheiro.name}: form possivelmente sem rota -> {action}"
                )

        else:
            caminho = action.split("?")[0]

            if caminho.startswith("/") and caminho not in rotas:
                problemas.append(
                    f"{ficheiro.name}: form sem rota -> {action}"
                )

    # -----------------------------------------------------
    # Botões potencialmente mortos
    # -----------------------------------------------------
    botoes = re.findall(
        r'<button([^>]*)>(.*?)</button>',
        texto,
        flags=re.I | re.S
    )

    for atributos, conteudo in botoes:
        conteudo_limpo = re.sub(
            r"<[^>]+>",
            " ",
            conteudo
        )
        conteudo_limpo = " ".join(conteudo_limpo.split())

        # submit dentro de form é válido
        if 'type="submit"' in atributos or "type='submit'" in atributos:
            continue

        # JavaScript explícito
        if "onclick=" in atributos:
            continue

        # alguns botões podem depender de JS por id/class
        if "id=" in atributos:
            avisos.append(
                f"{ficheiro.name}: verificar botão com JS -> {conteudo_limpo or '[sem texto]'}"
            )
            continue

        # botão normal sem comportamento evidente
        if 'type="button"' in atributos or "type='button'" in atributos:
            avisos.append(
                f"{ficheiro.name}: botão possivelmente inativo -> {conteudo_limpo or '[ícone]'}"
            )

# ---------------------------------------------------------
# 5. Ícones / links vazios
# ---------------------------------------------------------
for ficheiro in templates:
    texto = ficheiro.read_text(errors="ignore")

    if 'href="#"' in texto or "href='#'" in texto:
        avisos.append(
            f"{ficheiro.name}: existe href=\"#\""
        )

    vazios = re.findall(
        r'<a[^>]*href=["\']\s*["\'][^>]*>',
        texto,
        flags=re.I
    )

    if vazios:
        avisos.append(
            f"{ficheiro.name}: {len(vazios)} link(s) com href vazio"
        )

# ---------------------------------------------------------
# 6. Testes HTTP básicos
# ---------------------------------------------------------
print("\n--- TESTE HTTP ---")

client = app.test_client()

# tentar autenticação Paulo
login_ok = False

for login_url in ["/login", "/entrar"]:
    if login_url in rotas:
        try:
            r = client.post(
                login_url,
                data={
                    "username": "paulo",
                    "password": "1234",
                },
                follow_redirects=False,
            )

            if r.status_code in (200, 302, 303):
                login_ok = True
                print(
                    f"✅ tentativa de login Admin em {login_url}: HTTP {r.status_code}"
                )
            else:
                print(
                    f"⚠ login {login_url}: HTTP {r.status_code}"
                )

        except Exception as e:
            print(f"⚠ login não testado: {e}")

        break

if not login_ok:
    print("⚠ autenticação automática não confirmada")

for rota in sorted(rotas_get):
    if rota.startswith("/static/"):
        continue

    try:
        r = client.get(
            rota,
            follow_redirects=False
        )

        status = r.status_code

        if status >= 500:
            problemas.append(
                f"HTTP {status}: GET {rota}"
            )
        elif status == 404:
            problemas.append(
                f"HTTP 404: GET {rota}"
            )
        elif status in (301, 302, 303, 307, 308):
            print(f"↪ {rota:<30} {status}")
        elif status in (401, 403):
            print(f"🔒 {rota:<30} {status}")
        else:
            print(f"✅ {rota:<30} {status}")

    except Exception as e:
        problemas.append(
            f"GET {rota}: EXCEÇÃO {type(e).__name__}: {e}"
        )

# ---------------------------------------------------------
# RESULTADO
# ---------------------------------------------------------
print("\n==============================")
print("RESULTADO")
print("==============================")

if problemas:
    print(f"\n❌ PROBLEMAS: {len(problemas)}")
    for p in sorted(set(problemas)):
        print(" -", p)
else:
    print("\n✅ Nenhum link/rota claramente partido encontrado.")

if avisos:
    print(f"\n⚠ A VERIFICAR: {len(set(avisos))}")
    for a in sorted(set(avisos)):
        print(" -", a)
else:
    print("\n✅ Nenhum botão ou ícone suspeito encontrado.")

print("\n=== FIM DA AUDITORIA ===")
