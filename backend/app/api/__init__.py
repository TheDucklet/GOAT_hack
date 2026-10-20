from . import admin_accounts, admin_jobs, auth, companies, jobs, memberships

routers = (
    auth.router,
    memberships.router,
    admin_accounts.router,
    companies.router,
    jobs.router,
    admin_jobs.router,
)
