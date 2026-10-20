from . import (
    admin_accounts,
    admin_jobs,
    admin_materials,
    admin_stats,
    auth,
    companies,
    content,
    jobs,
    memberships,
)

routers = (
    auth.router,
    memberships.router,
    admin_accounts.router,
    companies.router,
    jobs.router,
    admin_jobs.router,
    admin_materials.router,
    content.router,
    admin_stats.router,
)
