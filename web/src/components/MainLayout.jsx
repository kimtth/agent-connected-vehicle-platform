import { useState } from 'react';
import { 
  Menu, X, LogOut, LogIn, LayoutDashboard, MessageCircle, 
  Rocket, Volume2, Settings, Lock, Info, User, Component, Bell, ChevronDown 
} from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { AuthenticatedTemplate, UnauthenticatedTemplate, useMsal } from '@azure/msal-react';
import { loginRequest } from '../auth/msalConfig';

const MainLayout = ({ children, vehicles = [], selectedVehicle, onVehicleChange, themeMode, onToggleTheme }) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const { instance, accounts } = useMsal();

  const handleDrawerToggle = () => setDrawerOpen(!drawerOpen);

  const handleVehicleChange = (value) => {
    const vehicle = vehicles.find(v => v.vehicleId === value);
    if (vehicle) onVehicleChange(vehicle);
  };

  const handleLogin = () => {
    instance.loginRedirect(loginRequest).catch((error) => console.error('Login error:', error));
  };

  const handleLogout = () => {
    instance.logoutRedirect().catch((error) => console.error('Logout error:', error));
  };

  const navigationItems = [
    { path: '/', icon: LayoutDashboard, text: 'Dashboard' },
    { path: '/agent-chat', icon: MessageCircle, text: 'Agent Chat' },
    { path: '/simulator', icon: Rocket, text: 'Car Simulator' },
    { path: '/remote-drive', icon: Component, text: 'Remote Drive' },
    { path: '/vehicle-assistant', icon: Volume2, text: 'Vehicle Assistant' },
    { path: '/services', icon: Settings, text: 'Services' },
    { path: '/notifications', icon: Bell, text: 'Notifications' },
  ];

  const systemItems = [
    { path: '/settings', icon: Settings, text: 'Settings' },
    { path: '/security', icon: Lock, text: 'Security' },
    { path: '/about', icon: Info, text: 'About' },
    { path: '/profile', icon: User, text: 'Profile' },
  ];

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 h-14 bg-primary text-primary-foreground border-b border-primary/20 z-50 px-3 shadow-sm">
        <div className="flex items-center justify-between h-full">
          <div className="flex items-center gap-2.5">
            <button 
              className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
              onClick={handleDrawerToggle}
            >
              <Menu className="h-4 w-4" />
            </button>
            <h1 className="text-lg font-semibold hidden sm:block">Agentic Connected Vehicle Platform</h1>
            <h1 className="text-lg font-semibold sm:hidden">ACVP</h1>
          </div>
          
          <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-2.5">
            {vehicles.length > 0 && (
              <div className="relative">
                <select 
                  value={selectedVehicle?.vehicleId || ''}
                  onChange={(e) => handleVehicleChange(e.target.value)}
                  className="min-w-[180px] px-2.5 py-1.5 text-sm border border-white/20 rounded-md bg-white/10 text-primary-foreground appearance-none pr-8 hover:bg-white/15 transition-colors"
                >
                  {vehicles.map((vehicle) => (
                    <option key={vehicle.vehicleId} value={vehicle.vehicleId} className="bg-background text-foreground">
                      {vehicle.make} {vehicle.model} ({vehicle.vehicleId})
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 pointer-events-none" />
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-2.5">
            {/* Dark mode toggle */}
            <button
              className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
              onClick={onToggleTheme}
              title={themeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {themeMode === 'dark' ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
              )}
            </button>
            <AuthenticatedTemplate>
              <div className="flex items-center gap-1.5">
                {accounts[0] && (
                  <span className="text-xs hidden">
                    {accounts[0].name || accounts[0].username}
                  </span>
                )}
                <button 
                  className="px-2.5 py-1.5 text-sm rounded-md bg-white/10 hover:bg-white/20 inline-flex items-center gap-1.5 transition-colors"
                  onClick={handleLogout}
                >
                  <LogOut className="h-3.5 w-3.5" /> Sign Out
                </button>
              </div>
            </AuthenticatedTemplate>
            
            <UnauthenticatedTemplate>
              <button 
                className="px-2.5 py-1.5 text-sm rounded-md bg-white/10 hover:bg-white/20 inline-flex items-center gap-1.5 transition-colors"
                onClick={handleLogin}
              >
                <LogIn className="h-3.5 w-3.5" /> Sign In
              </button>
            </UnauthenticatedTemplate>
          </div>
        </div>
      </header>


      {/* Drawer */}
      {drawerOpen && (
        <>
          <div 
            className="fixed inset-0 bg-black/50 z-40 animate-fadeIn"
            onClick={handleDrawerToggle}
          />
          <nav 
            className="fixed top-0 left-0 bottom-0 w-[250px] bg-card border-r z-50 overflow-y-auto p-3 animate-slideIn"
          >
            <div className="flex justify-end mb-3">
              <button 
                className="p-1.5 rounded-md hover:bg-accent"
                onClick={handleDrawerToggle}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            
            <div className="flex flex-col gap-1">
              {navigationItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Link key={item.path} to={item.path} className="no-underline">
                    <button 
                      className={`w-full px-3 py-2 text-sm rounded-md text-left inline-flex items-center gap-1.5 font-medium transition-colors ${
                        location.pathname === item.path 
                          ? 'bg-primary text-primary-foreground' 
                          : 'hover:bg-accent'
                      }`}
                      onClick={handleDrawerToggle}
                    >
                      <Icon className="h-3.5 w-3.5" /> {item.text}
                    </button>
                  </Link>
                );
              })}
            </div>
            
            <div className="h-px bg-border my-3" />
            
            <div className="flex flex-col gap-1">
              {systemItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Link key={item.path} to={item.path} className="no-underline">
                    <button 
                      className={`w-full px-3 py-2 text-sm rounded-md text-left inline-flex items-center gap-1.5 font-medium transition-colors ${
                        location.pathname === item.path 
                          ? 'bg-primary text-primary-foreground' 
                          : 'hover:bg-accent'
                      }`}
                      onClick={handleDrawerToggle}
                    >
                      <Icon className="h-3.5 w-3.5" /> {item.text}
                    </button>
                  </Link>
                );
              })}
            </div>
          </nav>
        </>
      )}

      {/* Main Content */}
      <main className="pt-16 p-5">
        {children}
      </main>
    </div>
  );
};

export default MainLayout;
