from datetime import datetime
import time
from pathlib import Path
from random import random
from typing import Optional, Dict, List, Any

import jinja2
from jinja2 import Environment, FileSystemLoader
from starlette.requests import Request
from starlette.responses import HTMLResponse
from toomanysessions import User
from toomanythreads import ThreadedServer
from loguru import logger as log

from fastcloudflare.src.fastcloudflare import Cloudflare, GatewayPyzure
from fastcloudflare.src.fastcloudflare.cloudflare_api import CloudflareAPI

def populate_user_profile(
    full_name: str,
    email: str,
    job_title: str,
    department: str,
    employee_id: Optional[str] = None,
    manager: Optional[str] = None,
    location: Optional[str] = None,
    start_date: Optional[str] = None,
    work_phone: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    office_location: Optional[str] = None,
    time_zone: Optional[str] = None,
    working_hours: Optional[str] = None,
    security_clearance: Optional[str] = None,
    ad_group: Optional[str] = None,
    vpn_access: Optional[str] = None,
    mfa_status: Optional[str] = None,
    last_password_change: Optional[str] = None,
    status: Optional[str] = None,
    profile_picture_color: Optional[str] = None,
    recent_activities: Optional[List[Dict[str, str]]] = None,
    action_buttons: Optional[List[Dict[str, str]]] = None,
    actions_title: Optional[str] = None,
    title: Optional[str] = None,
    verbose: bool = False
):
    """
    Populate user profile template variables for Microsoft user page.

    Args:
        full_name: User's full name (required)
        email: User's email address (required)
        job_title: User's job title (required)
        department: User's department (required)
        employee_id: Employee ID (auto-generated if not provided)
        manager: Manager's name
        location: Work location
        start_date: Employment start date
        work_phone: Work phone number
        mobile_phone: Mobile phone number
        office_location: Office building/floor location
        time_zone: User's time zone
        working_hours: Working hours
        security_clearance: Security clearance level
        ad_group: Active Directory group
        vpn_access: VPN access status
        mfa_status: Multi-factor authentication status
        last_password_change: Last password change date
        status: Current status (Available, Away, etc.)
        profile_picture_color: Background gradient for profile picture
        recent_activities: List of recent activity dicts
        action_buttons: List of action button dicts
        actions_title: Title for actions section
        title: Page title
        verbose: Enable verbose logging

    Returns:
        Dict containing all template variables for the user profile page
    """

    if verbose:
        log.info(f"Populating user profile for {full_name}")

    # Generate initials from full name
    name_parts = full_name.strip().split()
    initials = ''.join([part[0].upper() for part in name_parts[:2]])

    # Auto-generate employee ID if not provided
    if not employee_id:
        employee_id = 6
        if verbose:
            log.debug(f"Generated employee ID: {employee_id}")

    # Default recent activities if not provided
    if not recent_activities:
        recent_activities = [
            {"icon": "📧", "text": "Accessed Outlook Web App", "time": "2 min ago"},
            {"icon": "📊", "text": "Updated PowerBI dashboard", "time": "1 hour ago"},
            {"icon": "💬", "text": "Joined Teams meeting", "time": "3 hours ago"},
            {"icon": "📁", "text": "Modified SharePoint document", "time": "Yesterday"}
        ]

    # Default action buttons if not provided
    if not action_buttons:
        action_buttons = [
            {"text": "Edit Profile", "class": "", "onclick": ""},
            {"text": "Change Password", "class": "secondary", "onclick": ""},
            {"text": "Security Settings", "class": "secondary", "onclick": ""},
            {"text": "Download Data", "class": "secondary", "onclick": ""}
        ]

    # Build the template data dictionary
    template_data = {
        "title": title or f"{full_name} - User Profile",
        "initials": initials,
        "full_name": full_name,
        "email": email,
        "job_title": job_title,
        "department": department,
        "employee_id": employee_id,
        "manager": manager or "Not Assigned",
        "location": location or "Remote",
        "start_date": start_date or "Not Specified",
        "work_phone": work_phone or "Not Provided",
        "mobile_phone": mobile_phone or "Not Provided",
        "office_location": office_location or "Remote Worker",
        "time_zone": time_zone or "UTC",
        "working_hours": working_hours or "9:00 AM - 5:00 PM",
        "security_clearance": security_clearance or "Standard",
        "ad_group": ad_group or f"{department.replace(' ', '')}Users",
        "vpn_access": vpn_access or "Enabled",
        "mfa_status": mfa_status or "Enabled",
        "last_password_change": last_password_change or datetime.now().strftime("%B %d, %Y"),
        "status": status or "Available",
        "profile_picture_color": profile_picture_color or "linear-gradient(135deg, #0078d4 0%, #005a9e 100%)",
        "recent_activities": recent_activities,
        "action_buttons": action_buttons,
        "actions_title": actions_title or "Account Actions"
    }

    if verbose:
        log.info(f"Profile populated successfully with {len(template_data)} fields")
        log.debug(f"Generated initials: {initials}")
        log.debug(f"AD Group: {template_data['ad_group']}")

    templater = Environment(loader=FileSystemLoader(Path(__file__).parent))
    template = templater.get_template("user.html")
    return template.render(template_data)

if __name__ == "__main__":
    app = ThreadedServer()
    c = GatewayPyzure(app, tenant_whitelist=["e58f9482-1a00-4559-b3b7-42cd6038c43e"])
    @app.get("/")
    def my_user(request: Request):
        session = c.session_manager(request)
        if not session: c.popup_error(404, "User could not be found!")
        user: User = session.user
        return HTMLResponse(populate_user_profile(user.me.displayName, user.me.userPrincipalName, "miles' job title", "department"))
    c.launch()

    time.sleep(500000)