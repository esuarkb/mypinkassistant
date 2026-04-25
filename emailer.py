import os
import requests
from html import escape

def send_welcome_email(to_email: str, first_name: str = "", lang: str = "en") -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()  # e.g. "MyPinkAssistant <support@mypinkassistant.com>"
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    lang = (lang or "en").strip().lower()
    if lang not in ("en", "es"):
        lang = "en"

    name = (first_name or "").strip() or ("there" if lang == "en" else "")
    safe_name = escape(name)

    if lang == "es":
        subject = "¡Bienvenida a MyPinkAssistant.com — aquí tienes tus consejos iniciales! ✨"

        text = f"""¡Hola {name}!

¡Bienvenida a MyPinkAssistant — estamos muy contentos de tenerte aquí!

Comienza a chatear ahora: https://mypinkassistant.com

Aquí tienes algunos consejos rápidos para empezar:

AGREGAR UN NUEVO CLIENTE
Incluye tanto o tan poco como quieras: nombre, dirección, correo electrónico, teléfono, cumpleaños.

Ejemplo:
Nueva cliente Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02

Lo organizaré y lo enviaré a MyCustomers automáticamente.

BUSCAR UN CLIENTE
Solo escribe un nombre — encontraré la coincidencia más cercana aunque lo escribas mal.

Ejemplo:
Jane Doe
¿Cuáles fueron los últimos 3 pedidos de Jane?

AGREGAR UN PEDIDO DE CLIENTE
Agrega varios artículos y cantidades en un solo mensaje — confirmaré todo antes de enviarlo.

Ejemplo:
Nuevo pedido para Jane Doe; quiere un labial rojo, 2 máscaras de carbón y un limpiador 4-en-1 para piel normal/seca.

INVENTARIO PERSONAL
Cuando hagas un pedido de inventario a través de MaryKayInTouch.com, tu stock se actualiza automáticamente — sin necesidad de entrada manual. También puedes consultar el stock, actualizar cantidades, configurar alertas de stock bajo e imprimir un PDF en cualquier momento con solo pedirlo.

Ejemplo:
¿Cuántos sets TimeWise tengo? Establece mi par para máscaras de carbón en 3.

PROGRAMA DE REFERIDOS
¡Da un mes, gana un mes! Tu enlace de referido personal está en Configuración en https://mypinkassistant.com

SÍGUENOS EN FACEBOOK
Consejos, nuevas funciones y actualizaciones: https://www.facebook.com/mypinkassistant1

¿Tienes preguntas? Consulta nuestras Preguntas Frecuentes: https://mypinkassistant.com/faq

Creamos MyPinkAssistant para ahorrarte tiempo y simplificar tu negocio — y es un honor tenerte aquí.

¿Necesitas ayuda o tienes una solicitud de función?
support@mypinkassistant.com
"""

        html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">¡Hola {safe_name}!</p>

      <h2 style="margin:0 0 12px 0;font-size:22px;line-height:1.25;">
        Bienvenida a <strong>MyPinkAssistant</strong> 💕
      </h2>

      <p style="margin:0 0 16px 0;">
        Puede que ya hayas entrado — pero si no, puedes empezar aquí:
      </p>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Comenzar a Chatear
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:10px;"></div>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">💁‍♀️ Agregar un Nuevo Cliente</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Incluye tanto o tan poco detalle como quieras: nombre, dirección, correo electrónico, número de teléfono, cumpleaños.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        Nueva cliente Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        Organizaré lo que ingreses y lo enviaré a <strong>MyCustomers</strong> automáticamente.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📇 Buscar Información de Clientes y Pedidos</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Encuentra instantáneamente los detalles del cliente y los pedidos anteriores — solo escribe un nombre.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        Jane Doe<br>
        ¿Cuáles fueron los últimos 3 pedidos de Jane?
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        Encontraré la coincidencia más cercana aunque no recuerdes la ortografía exacta.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🛍 Agregar un Pedido de Cliente</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Agrega varios artículos y cantidades en un solo mensaje — no se necesitan números de SKU.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        Nuevo pedido para Jane Doe; quiere un labial rojo, 2 máscaras de carbón y un limpiador 4-en-1 para piel normal/seca.
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        Confirmaré cada artículo antes de enviarlo, y siempre puedes agregar o quitar artículos antes de la aprobación final.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📦 Inventario Personal</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Cuando hagas un pedido de inventario a través de MaryKayInTouch.com, tu stock se actualiza automáticamente — sin necesidad de entrada manual. También puedes consultar el stock, actualizar cantidades, configurar alertas de stock bajo e imprimir un PDF en cualquier momento con solo pedirlo.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        ¿Cuántos sets TimeWise tengo? Establece mi par para máscaras de carbón en 3.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Programa de Referidos</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        ¡Da un mes, gana un mes! Tu enlace de referido personal está en <strong>Configuración</strong>.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Síguenos en Facebook</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Síguenos en Facebook para consejos, nuevas funciones y actualizaciones:
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">facebook.com/mypinkassistant1</a>
      </p>

      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        Creamos MyPinkAssistant para ahorrarte tiempo y simplificar tu negocio — y es un honor tenerte aquí. 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        ¿Tienes preguntas? Consulta nuestras <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">Preguntas Frecuentes</a> o escríbenos a
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>.
      </p>

      <p style="margin:10px 0 0 0;font-size:12px;color:#5a5a5a;">
        Abre MyPinkAssistant en cualquier momento: <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">
          mypinkassistant.com
        </a>
      </p>
    </div>
  </body>
</html>
"""

    else:
        subject = "Welcome to MyPinkAssistant.com — here are your starter tips! ✨"

        text = f"""Hi {name}!

Welcome to MyPinkAssistant — we’re so glad you’re here!

Start chatting now: https://mypinkassistant.com

Here are a few quick starter tips:

ADD A NEW CUSTOMER
Include as much or as little as you want: name, address, email, phone, birthday.

Example:
New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02

I’ll organize it and get it ready to send to MyCustomers automatically.

LOOK UP A CUSTOMER
Just type a name — I’ll find the closest match even if you misspell it. Your existing customers and order history from MyCustomers are imported automatically when you sign up, so you can look up past orders right away.

Example:
Jane Doe
What were Jane’s last 3 orders?

ADD A CUSTOMER ORDER
Add multiple items and quantities in one message — I’ll confirm everything before submitting.

Example:
New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.

PERSONAL INVENTORY
When you place an inventory order through MaryKayInTouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.

Example:
How many TimeWise sets do I have? Set my par for charcoal masks to 3.

REFERRAL PROGRAM
Give a month, get a month! Your referral link is in Settings at https://mypinkassistant.com

FOLLOW US ON FACEBOOK
Tips, new features, and updates: https://www.facebook.com/mypinkassistant1

Have questions? Check out our FAQ: https://mypinkassistant.com/faq

We built MyPinkAssistant to save you time and simplify your business - and we’re honored you’re here.

Need help or have a feature request?
support@mypinkassistant.com
"""

        html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">Hi {safe_name}!</p>

      <h2 style="margin:0 0 12px 0;font-size:22px;line-height:1.25;">
        Welcome to <strong>MyPinkAssistant</strong> 💕
      </h2>

      <p style="margin:0 0 16px 0;">
        You may have already jumped in — but if not, you can start here:
      </p>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Start Chatting
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:16px;margin-top:10px;"></div>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">💁‍♀️ Add a New Customer</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Include as much or as little detail as you’d like: name, address, email, phone number, birthday.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll organize what you enter and send it to <strong>MyCustomers</strong> automatically.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📇 Look up Customer Information and Orders</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Instantly find customer details and past orders — just type a name. Your existing customers and order history from MyCustomers are imported automatically when you sign up, so you can look up past orders right away.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        Jane Doe<br>
        What were Jane’s last 3 orders?
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll find the closest match even if you don’t remember the exact spelling.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🛍 Add a Customer Order</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Add multiple items and quantities in one message — no SKU numbers needed.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.
      </p>
      <p style="margin:0 0 16px 0;color:#111;">
        I’ll confirm each item before submitting, and you can always add/remove before final approval.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📦 Personal Inventory</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        When you place an inventory order through MaryKayInTouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        How many TimeWise sets do I have? Set my par for charcoal masks to 3.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Referral Program</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Give a month, get a month! Your personal referral link is in <strong>Settings</strong>.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Follow Us on Facebook</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Follow our Facebook page for tips, new features, and updates:
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">facebook.com/mypinkassistant1</a>
      </p>

      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        We built MyPinkAssistant to save you time and simplify your business — and we’re honored you’re here. 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Have questions? Check out our <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">FAQ</a> or email us at
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>.
      </p>

      <p style="margin:10px 0 0 0;font-size:12px;color:#5a5a5a;">
        Open MyPinkAssistant anytime: <a href="https://mypinkassistant.com" style="color:#e91e63;text-decoration:none;">
          mypinkassistant.com
        </a>
      </p>
    </div>
  </body>
</html>
"""

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")


def send_wrong_credentials_email(to_email: str, first_name: str = "", lang: str = "en") -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    lang = (lang or "en").strip().lower()
    if lang not in ("en", "es"):
        lang = "en"

    name = (first_name or "").strip() or ("there" if lang == "en" else "")
    safe_name = escape(name)

    if lang == "es":
        subject = "MyPinkAssistant — credenciales de InTouch incorrectas"

        text = f"""¡Hola {name}!

Parece que guardaste el usuario o la contraseña incorrectos de InTouch en MyPinkAssistant. Puedes corregirlo en mypinkassistant.com/settings — solo vuelve a ingresar las credenciales correctas, presiona Guardar y regresa al chat para comenzar.

¡Avísame si tienes algún otro problema!

-Brian
support@mypinkassistant.com
"""

        html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">¡Hola {safe_name}!</p>

      <p style="margin:0 0 16px 0;">
        Parece que guardaste el usuario o la contraseña incorrectos de InTouch en MyPinkAssistant. Puedes corregirlo en unos pocos pasos:
      </p>

      <ol style="margin:0 0 16px 0;padding-left:20px;color:#111;">
        <li style="margin-bottom:6px;">Toca el botón de abajo para abrir Configuración</li>
        <li style="margin-bottom:6px;">Vuelve a ingresar tu usuario y contraseña correctos de InTouch</li>
        <li style="margin-bottom:6px;">Presiona <strong>Guardar</strong> y regresa al chat para comenzar</li>
      </ol>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com/settings"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Ir a Configuración
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:10px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        ¡Gracias por usar MyPinkAssistant! Estamos aquí si tienes preguntas, sugerencias o problemas —
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>
      </p>

      <p style="margin:6px 0 0 0;font-size:13px;color:#5a5a5a;">-Brian</p>
    </div>
  </body>
</html>
"""

    else:
        subject = "MyPinkAssistant — incorrect InTouch credentials"

        text = f"""Hi {name}!

It looks like you might have saved the wrong InTouch username or password in MyPinkAssistant. You can fix this at mypinkassistant.com/settings — just re-enter the correct credentials, hit Save, and head back to chat to get started.

Let me know if you have any other issues!

-Brian
support@mypinkassistant.com
"""

        html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <p style="margin:0 0 12px 0;">Hi {safe_name}!</p>

      <p style="margin:0 0 16px 0;">
        It looks like you might have saved the wrong InTouch username or password in MyPinkAssistant. You can fix this in just a few steps:
      </p>

      <ol style="margin:0 0 16px 0;padding-left:20px;color:#111;">
        <li style="margin-bottom:6px;">Tap the button below to open Settings</li>
        <li style="margin-bottom:6px;">Re-enter your correct InTouch username and password</li>
        <li style="margin-bottom:6px;">Hit <strong>Save</strong>, then head back to chat to get started</li>
      </ol>

      <p style="margin:0 0 22px 0;">
        <a href="https://mypinkassistant.com/settings"
           style="display:inline-block;background:#e91e63;color:#ffffff;text-decoration:none;
                  padding:12px 16px;border-radius:10px;font-weight:bold;">
          Go to Settings
        </a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:10px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Thank you for using MyPinkAssistant! We are here if you have any questions, suggestions, or issues! —
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>
      </p>

      <p style="margin:6px 0 0 0;font-size:13px;color:#5a5a5a;">-Brian</p>
    </div>
  </body>
</html>
"""

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")


def send_login_failure_alert_email(to_email: str, consultant_id: int, consultant_name: str, consultant_email: str, error: str) -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    subject = f"MyPinkAssistant — Login Failure (Consultant {consultant_id})"
    safe_error = escape(error)

    html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <h2 style="margin:0 0 12px 0;font-size:18px;">&#128680; InTouch Login Failure</h2>
      <p style="margin:0 0 8px 0;"><strong>Consultant:</strong> {escape(consultant_name)} ({escape(consultant_email)}) ID {consultant_id}</p>
      <p style="margin:0 0 8px 0;"><strong>Error:</strong></p>
      <p style="margin:0 0 16px 0;padding:10px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:8px;font-size:13px;">{safe_error}</p>
      <p style="margin:0;font-size:13px;color:#5a5a5a;">This will auto-resolve once the consultant updates their credentials in Settings.</p>
    </div>
  </body>
</html>"""

    text = f"InTouch Login Failure\n\nConsultant: {consultant_name} ({consultant_email}) ID {consultant_id}\nError: {error}\n\nThis will auto-resolve once the consultant updates their credentials."

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")