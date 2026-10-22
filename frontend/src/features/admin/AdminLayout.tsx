import { NavLink, Outlet } from 'react-router-dom';

export function AdminLayout() {
  return <div className="admin-workspace"><nav className="admin-nav" aria-label="Администрирование">
    <NavLink to="/admin" end>Обзор</NavLink><NavLink to="/admin/users" end>Пользователи</NavLink><NavLink to="/admin/memberships">Заявки и доступ</NavLink>
  </nav><Outlet /></div>;
}
