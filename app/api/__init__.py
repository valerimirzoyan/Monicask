from app.api.routes_admin import router as admin_router
from app.api.routes_agent import router as agent_router
from app.api.routes_tickets import router as tickets_router
from app.api.routes_webhook import router as webhook_router

__all__ = ["admin_router", "agent_router", "tickets_router", "webhook_router"]
