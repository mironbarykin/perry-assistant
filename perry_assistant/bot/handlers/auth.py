from telegram import Update
from telegram.ext import CallbackContext, ContextTypes
import pickle
from google_auth_oauthlib.flow import Flow
from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin

async def send_auth_link_to_admin(context: ContextTypes.DEFAULT_TYPE, reason: str) -> None:
    services = context.application.bot_data["services"]
    flow = Flow.from_client_secrets_file(
        str(services.config.credentials_file),
        scopes=list(services.config.scopes),
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    context.application.bot_data["pending_auth"] = {"flow": flow, "awaiting_code": True}
    await context.bot.send_message(
        chat_id=services.config.miron_id,
        text=(
            f"Google authorization required: {reason}\n\n"
            f"Open this link and send the code back in chat:\n{auth_url}"
        ),
    )


@require_admin
async def handle_auth_code(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    code = update.message.text.strip()
    services = get_services(context)
    pending = context.application.bot_data.get("pending_auth")
    if not pending or not pending.get("awaiting_code"):
        return

    try:
        flow = pending["flow"]
        flow.fetch_token(code=code)
        with services.config.token_pickle_file.open("wb") as token_file:
            pickle.dump(flow.credentials, token_file)
        services.referee_service.refresh_google_clients()
        context.application.bot_data["pending_auth"] = None
        await update.message.reply_text("Google authentication updated.")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Authentication failed: {exc}")
