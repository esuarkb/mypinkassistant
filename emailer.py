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

BUSCAR UN PRODUCTO
Pregunta por cualquier producto por su nombre y te mostraré el precio, el número de pieza, los tonos, los ingredientes y las hojas de datos — sin buscar en el catálogo.

Ejemplo:
Cuéntame sobre la base TimeWise 3D
¿Cuáles son los ingredientes de la máscara de carbón?

HAZ PREGUNTAS SOBRE TU NEGOCIO
Pregunta sobre tus clientas y sus pedidos en lenguaje natural — yo busco la respuesta.

Ejemplo:
¿Quién no ha pedido en 6 meses?
¿Quién compró la máscara de carbón?

INVENTARIO PERSONAL
Cuando hagas un pedido de inventario a través de MaryKayInTouch.com, tu stock se actualiza automáticamente — sin necesidad de entrada manual. También puedes consultar el stock, actualizar cantidades, configurar alertas de stock bajo e imprimir un PDF en cualquier momento con solo pedirlo.

Ejemplo:
¿Cuántos sets TimeWise tengo? Establece mi par para máscaras de carbón en 3.

DIRECTORAS
Si tienes una unidad, tu equipo también está aquí — miembros de la unidad, Great Start, Star Consultant y el programa de auto. Solo pregunta.

PROGRAMA DE REFERIDOS
¡Da un mes, gana un mes! Tu enlace de referido personal está en Configuración en https://mypinkassistant.com

SÍGUENOS EN FACEBOOK, INSTAGRAM Y TIKTOK
Facebook: https://www.facebook.com/mypinkassistant1
Instagram: https://www.instagram.com/mypinkassistant
TikTok: https://www.tiktok.com/@mypinkassistant

¿Tienes preguntas? La página de Ayuda tiene una guía rápida de todo lo que puedes decir en el chat: https://mypinkassistant.com/help
Nuestras Preguntas Frecuentes cubren el resto: https://mypinkassistant.com/faq

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

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🔍 Buscar un Producto</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Pregunta por cualquier producto por su nombre y te mostraré el precio, el número de pieza, los tonos, los ingredientes y las hojas de datos — sin buscar en el catálogo.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        Cuéntame sobre la base TimeWise 3D<br>
        ¿Cuáles son los ingredientes de la máscara de carbón?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">💬 Haz Preguntas Sobre Tu Negocio</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Pregunta sobre tus clientas y sus pedidos en lenguaje natural — yo busco la respuesta.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        ¿Quién no ha pedido en 6 meses?<br>
        ¿Quién compró la máscara de carbón?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📦 Inventario Personal</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Cuando hagas un pedido de inventario a través de MaryKayInTouch.com, tu stock se actualiza automáticamente — sin necesidad de entrada manual. También puedes consultar el stock, actualizar cantidades, configurar alertas de stock bajo e imprimir un PDF en cualquier momento con solo pedirlo.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Ejemplo:</strong><br>
        ¿Cuántos sets TimeWise tengo? Establece mi par para máscaras de carbón en 3.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">👑 Directoras</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Si tienes una unidad, tu equipo también está aquí — miembros de la unidad, Great Start, Star Consultant y el programa de auto. Solo pregunta.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Programa de Referidos</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        ¡Da un mes, gana un mes! Tu enlace de referido personal está en <strong>Configuración</strong>.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Síguenos en Facebook, Instagram y TikTok</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Consejos, nuevas funciones y actualizaciones:<br>
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">facebook.com/mypinkassistant1</a><br>
        <a href="https://www.instagram.com/mypinkassistant" style="color:#e91e63;text-decoration:none;font-weight:bold;">instagram.com/mypinkassistant</a><br>
        <a href="https://www.tiktok.com/@mypinkassistant" style="color:#e91e63;text-decoration:none;font-weight:bold;">tiktok.com/@mypinkassistant</a>
      </p>

      <p style="margin:0 0 18px 0;font-size:15px;color:#111;font-weight:500;">
        Creamos MyPinkAssistant para ahorrarte tiempo y simplificar tu negocio — y es un honor tenerte aquí. 💗
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        ¿Tienes preguntas? La página de <a href="https://mypinkassistant.com/help" style="color:#e91e63;text-decoration:none;font-weight:bold;">Ayuda</a> tiene una guía rápida de todo lo que puedes decir en el chat, y nuestras <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">Preguntas Frecuentes</a> cubren el resto. O escríbenos a
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
What foundation does Jane use?
What were Jane’s last 3 orders?

ADD A CUSTOMER ORDER
Add multiple items and quantities in one message — I’ll confirm everything before submitting.

Example:
New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.

LOOK UP A PRODUCT
Ask about any product by name and I'll pull up the price, part number, shades, ingredients, and fact sheets — no catalog to dig through.

Example:
TimeWise 3D foundation
Charcoal Mask

PERSONAL INVENTORY
When you place an inventory order through MaryKayInTouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.

Example:
How many TimeWise sets do I have?
Set my par for charcoal masks to 3.

DIRECTORS
If you have a unit, your team is in here too — unit members, Great Start, Star Consultant, and the car program. Just ask.

REFERRAL PROGRAM
Give a month, get a month! Your referral link is in Settings at https://mypinkassistant.com

FOLLOW US ON FACEBOOK, INSTAGRAM & TIKTOK
Facebook: https://www.facebook.com/mypinkassistant1
Instagram: https://www.instagram.com/mypinkassistant
TikTok: https://www.tiktok.com/@mypinkassistant

Have questions? The Help page is a cheat sheet of everything you can say in chat: https://mypinkassistant.com/help
Our FAQ covers the rest: https://mypinkassistant.com/faq

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

      <p style="margin:0 0 14px 0;color:#111;">Here are some things you can do in chat:</p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">💁‍♀️ Add a New Customer</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Include as much or as little detail as you’d like: name, address, email, phone number, birthday. I’ll organize what you enter and send it to MyCustomers automatically.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New customer Jane Doe, 444 4th St, Anytown, Alabama 55555, jane@gmail.com, 5551231234, 12-25-02
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📇 Look up Customer Information and Orders</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Instantly find customer details and past orders — just type a name. Your existing customers and order history from MyCustomers are imported automatically when you sign up, so you can look up customers and past orders right away. I’ll find the closest match even if you don’t remember the exact spelling.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        Jane Doe<br>
        What foundation does Jane use?<br>
        What were Jane’s last 3 orders?
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🛍 Add a Customer Order</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Add multiple items and quantities in one message — no SKU numbers needed. I’ll confirm each item before submitting, and you can always add/remove before final approval.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        New order for Jane Doe; she wants a red lipstick, 2 charcoal masks, and a 4-in-1 cleanser for normal/dry.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🔍 Look up a Product</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        Ask about any product by name and I’ll pull up the price, part number, shades, ingredients, and fact sheets — no catalog to dig through.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        TimeWise 3D foundation<br>
        Charcoal Mask
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📦 Personal Inventory</h3>
      <p style="margin:0 0 10px 0;color:#111;">
        When you place an inventory order through marykayintouch.com, your stock updates automatically — no manual entry needed. You can also check stock, update quantities, set low-stock alerts, and print a PDF anytime just by asking.
      </p>
      <p style="margin:0 0 14px 0;padding:12px;background:#f7f7f8;border:1px solid #e6e6e6;border-radius:10px;">
        <strong>Example:</strong><br>
        How many TimeWise sets do I have?<br>
        Set my par for charcoal masks to 3.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">👑 Directors</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        If you have a unit, your team is in here too — unit members, Great Start, Star Consultant, and the car program. Just ask.
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">🎁 Referral Program</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Give a month, get a month! Your personal referral link is in <a href="https://mypinkassistant.com/settings" style="color:#e91e63;text-decoration:none;">Settings</a>.
      </p>

      <p style="margin:0 0 16px 0;font-size:15px;color:#111;font-weight:500;">
        We built MyPinkAssistant to save you time and simplify your business — and we’re honored you’re here. 💗
      </p>

      <h3 style="margin:16px 0 8px 0;font-size:16px;">📣 Follow Us on Facebook, Instagram & TikTok</h3>
      <p style="margin:0 0 16px 0;color:#111;">
        Tips, new features, and updates:<br>
        <a href="https://www.facebook.com/mypinkassistant1" style="color:#e91e63;text-decoration:none;font-weight:bold;">facebook.com/mypinkassistant1</a><br>
        <a href="https://www.instagram.com/mypinkassistant" style="color:#e91e63;text-decoration:none;font-weight:bold;">instagram.com/mypinkassistant</a><br>
        <a href="https://www.tiktok.com/@mypinkassistant" style="color:#e91e63;text-decoration:none;font-weight:bold;">tiktok.com/@mypinkassistant</a>
      </p>

      <div style="border-top:1px solid #e6e6e6;padding-top:14px;margin-top:18px;"></div>

      <p style="margin:10px 0 0 0;font-size:14px;color:#5a5a5a;">
        Have questions? The <a href="https://mypinkassistant.com/help" style="color:#e91e63;text-decoration:none;font-weight:bold;">Help</a> page is a cheat sheet of everything you can say in chat, and our <a href="https://mypinkassistant.com/faq" style="color:#e91e63;text-decoration:none;font-weight:bold;">FAQ</a> covers the rest. Or email us at
        <a href="mailto:support@mypinkassistant.com" style="color:#e91e63;text-decoration:none;">support@mypinkassistant.com</a>.
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


def send_sku_not_found_email(
    to_email: str,
    consultant_name: str,
    consultant_email: str,
    consultant_id: int,
    sku: str,
    product_name: str,
    customer_name: str,
    requeued_count: int,
) -> None:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    mail_from = (os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or MAIL_FROM")

    safe_consultant = escape(consultant_name)
    safe_consultant_email = escape(consultant_email)
    safe_sku = escape(sku)
    safe_product = escape(product_name)
    safe_customer = escape(customer_name)

    subject = f"MPA — SKU Not Found in MyCustomers: {sku}"

    requeued_note = (
        f"{requeued_count} other item(s) in the order were requeued and will be submitted automatically."
        if requeued_count > 0
        else "There were no other items in the order to requeue."
    )

    text = (
        f"SKU Not Found in MyCustomers\n\n"
        f"Consultant: {consultant_name} ({consultant_email}) ID {consultant_id}\n"
        f"Customer: {customer_name}\n"
        f"SKU: {sku}\n"
        f"Product: {product_name}\n\n"
        f"{requeued_note}\n\n"
        f"Please check InTouch to see if this item is discontinued. "
        f"If so, remove it from catalog/en.csv and catalog/es.csv."
    )

    html = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#ffffff;">
    <div style="max-width:600px;margin:0 auto;padding:20px;font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111;">
      <h2 style="margin:0 0 12px 0;font-size:18px;">&#128683; SKU Not Found in MyCustomers</h2>
      <p style="margin:0 0 8px 0;"><strong>Consultant:</strong> {safe_consultant} ({safe_consultant_email}) ID {consultant_id}</p>
      <p style="margin:0 0 8px 0;"><strong>Customer:</strong> {safe_customer}</p>
      <p style="margin:0 0 8px 0;"><strong>SKU:</strong> {safe_sku}</p>
      <p style="margin:0 0 16px 0;"><strong>Product:</strong> {safe_product}</p>
      <p style="margin:0 0 12px 0;padding:10px;background:#fff3cd;border:1px solid #ffc107;border-radius:8px;">
        {escape(requeued_note)}
      </p>
      <p style="margin:0 0 8px 0;font-size:13px;color:#5a5a5a;">
        Check InTouch to see if this item is discontinued. If so, remove it from
        <code>catalog/en.csv</code> and <code>catalog/es.csv</code>.
      </p>
    </div>
  </body>
</html>"""

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

def send_admin_alert_email(subject: str, message: str) -> None:
    """Plain-text ops alert to the support inbox (2026-07-12). Used for
    lower-urgency alerts Brian routed OFF push/SMS — first user: report-sync
    degraded (worker.py). Never raises: alert paths must not die on email."""
    import requests as _requests
    try:
        api_key = (os.getenv("RESEND_API_KEY") or "").strip()
        mail_from = (os.getenv("MAIL_FROM") or "").strip()
        if not api_key or not mail_from:
            print("[AdminAlertEmail] Missing RESEND_API_KEY or MAIL_FROM")
            return
        r = _requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": mail_from, "to": ["support@mypinkassistant.com"],
                  "subject": subject, "text": message},
            timeout=15,
        )
        if r.status_code >= 300:
            print(f"[AdminAlertEmail] Resend error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[AdminAlertEmail] send failed: {e}")


def send_invoice_email(to_email: str, customer_name: str, consultant_name: str,
                       consultant_email: str, invoice_html: str,
                       pdf_bytes: bytes | None, invoice_date: str) -> None:
    """Email an invoice to a CUSTOMER (2026-08-04).

    Every other sender in this file writes to a consultant — someone who
    signed up with us and expects our name in the inbox. This one writes to
    her customer, who has never heard of MyPinkAssistant and did not opt into
    anything from us. Two consequences, both deliberate:

    FROM carries HER name over OUR domain: "Jane Smith <invoices@...>".
    Sending as her actual address would fail SPF/DKIM and land in spam; a
    bare MyPinkAssistant sender makes her customer think MK is invoicing
    them. The display name is the part a phone shows, so the customer sees
    "Jane Smith" and the domain quietly does the deliverability work. This is
    the same shape Shopify and Square use for merchant mail.

    REPLY-TO is her real address. A customer replying with "can I swap the
    lipstick shade" must reach HER, not our support inbox. This is the only
    reply_to in the codebase and the reason the feature is safe to ship: we
    are the transport, never a party to the conversation.

    The PDF is an attachment AND the invoice is inline in the body. Nobody
    should have to open a file to read a five-line receipt, and pdf_bytes is
    allowed to be None (see invoice.render_invoice_pdf) — a failed render
    costs the attachment, not the email.
    """
    import base64
    import re

    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    # Separate from MAIL_FROM on purpose: that one is the support identity.
    mail_from = (os.getenv("INVOICE_MAIL_FROM") or os.getenv("MAIL_FROM") or "").strip()
    if not api_key or not mail_from:
        raise RuntimeError("Missing RESEND_API_KEY or INVOICE_MAIL_FROM/MAIL_FROM")

    # If INVOICE_MAIL_FROM already carries a display name, strip it — hers wins.
    addr = mail_from.split("<")[-1].strip(" <>")
    # Quotes and newlines in a display name are header injection; her name
    # comes from the consultants table, but that is still user-typed text.
    display = (consultant_name or "").replace('"', "").replace("\n", " ").replace("\r", " ").strip()
    sender = f'{display} <{addr}>' if display else mail_from

    first = (customer_name or "").split()[0] if customer_name else "there"
    subject = f"Your Mary Kay invoice from {display}" if display else "Your Mary Kay invoice"

    intro = (f"<p>Hi {escape(first)}, thank you for your order! "
             f"Your invoice is below and attached as a PDF.</p>")
    body_html = invoice_html.replace("<body>", f"<body>{intro}", 1)

    text = f"Hi {first}, thank you for your order!\n\nYour invoice is attached as a PDF."
    if display:
        text += f"\n\n— {display}"

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": text,
        "html": body_html,
    }
    if consultant_email:
        payload["reply_to"] = consultant_email
    if pdf_bytes:
        # Named for the order date, not the order id: the id is internal (a
        # global autoincrement across every consultant) and the customer sees
        # this filename in her downloads folder. Non-alphanumerics collapse to
        # dashes so "June 7, 2026" becomes invoice-June-7-2026.pdf on every
        # mail client and filesystem.
        _stamp = re.sub(r"[^A-Za-z0-9]+", "-", (invoice_date or "")).strip("-")
        payload["attachments"] = [{
            "filename": f"invoice-{_stamp}.pdf" if _stamp else "invoice.pdf",
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
        }]

    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")
