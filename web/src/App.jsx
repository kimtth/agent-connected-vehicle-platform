import { useState, useEffect, useCallback } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { getMsalInstance, isClientIdConfigured } from './auth/msalConfig';
import { fetchVehicles } from './api/vehicles';

// Import pages
import Dashboard from './pages/Dashboard';
import AgentChat from './components/AgentChat';
import VehicleAssistant from './components/VehicleAssistant';
import Simulator from './pages/Simulator';
import NotificationLog from './components/NotificationLog';
import ServiceInfo from './components/ServiceInfo';
import RemoteDrive from './components/RemoteDrive';
import MainLayout from './components/MainLayout';
import ProtectedRoute from './auth/ProtectedRoute';

function App() {
  const [themeMode, setThemeMode] = useState(() => {
    return localStorage.getItem('theme') || 'light';
  });
  const [isInitialized, setIsInitialized] = useState(false);
  const [vehicles, setVehicles] = useState([]);
  const [selectedVehicle, setSelectedVehicle] = useState(null);

  // Theme management - Tailwind dark mode
  useEffect(() => {
    localStorage.setItem('theme', themeMode);
    if (themeMode === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [themeMode]);

  const toggleTheme = () => {
    setThemeMode(prev => prev === 'dark' ? 'light' : 'dark');
  };

  // Initialize MSAL
  useEffect(() => {
    const init = async () => {
      if (isClientIdConfigured()) {
        const instance = getMsalInstance();
        if (instance) {
          await instance.initialize();
        }
      }
      setIsInitialized(true);
    };
    init();
  }, []);

  // Load vehicles after initialization
  const loadVehicles = useCallback(async () => {
    try {
      const data = await fetchVehicles();
      setVehicles(data);
      if (data.length > 0 && !selectedVehicle) {
        setSelectedVehicle(data[0]);
      }
    } catch (error) {
      console.error('Error loading vehicles:', error);
    }
  }, [selectedVehicle]);

  useEffect(() => {
    if (isInitialized) {
      loadVehicles();
    }
  }, [isInitialized, loadVehicles]);

  const handleVehicleChange = (vehicle) => {
    setSelectedVehicle(vehicle);
  };

  if (!isInitialized) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground">Loading application...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <MainLayout
        themeMode={themeMode}
        toggleTheme={toggleTheme}
        onToggleTheme={toggleTheme}
        vehicles={vehicles}
        selectedVehicle={selectedVehicle}
        onVehicleChange={handleVehicleChange}
      >
        <Routes>
          <Route path="/" element={
            <ProtectedRoute>
              <Dashboard selectedVehicle={selectedVehicle} />
            </ProtectedRoute>
          } />
          <Route path="/agent-chat" element={
            <ProtectedRoute>
              <AgentChat vehicleId={selectedVehicle?.vehicleId} />
            </ProtectedRoute>
          } />
          <Route path="/vehicle-assistant" element={
            <ProtectedRoute>
              <VehicleAssistant />
            </ProtectedRoute>
          } />
          <Route path="/simulator" element={
            <ProtectedRoute>
              <Simulator selectedVehicle={selectedVehicle?.vehicleId} />
            </ProtectedRoute>
          } />
          <Route path="/notifications" element={
            <ProtectedRoute>
              <NotificationLog vehicleId={selectedVehicle?.vehicleId} />
            </ProtectedRoute>
          } />
          <Route path="/services" element={
            <ProtectedRoute>
              <ServiceInfo vehicleId={selectedVehicle?.vehicleId} />
            </ProtectedRoute>
          } />
          <Route path="/remote-drive" element={
            <ProtectedRoute>
              <RemoteDrive />
            </ProtectedRoute>
          } />
          <Route path="/settings" element={
            <div className="container mx-auto max-w-4xl p-5">
              <div className="rounded-lg border bg-card p-5">
                <h1 className="mb-3 text-2xl font-bold">Settings</h1>
                <p className="mb-5 text-sm text-muted-foreground">Configure your application preferences and system settings.</p>
                <div className="flex flex-col gap-3">
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">General</h2>
                    <p className="text-xs text-muted-foreground">Manage general application settings and preferences.</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Notifications</h2>
                    <p className="text-xs text-muted-foreground">Configure notification preferences and alerts.</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Display</h2>
                    <p className="text-xs text-muted-foreground">Customize your display settings and theme preferences.</p>
                  </div>
                </div>
              </div>
            </div>
          } />
          <Route path="/security" element={
            <div className="container mx-auto max-w-4xl p-5">
              <div className="rounded-lg border bg-card p-5">
                <h1 className="mb-3 text-2xl font-bold">Security</h1>
                <p className="mb-5 text-sm text-muted-foreground">Manage your security settings and authentication options.</p>
                <div className="flex flex-col gap-3">
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Authentication</h2>
                    <p className="text-xs text-muted-foreground">Configure multi-factor authentication and login options.</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Privacy</h2>
                    <p className="text-xs text-muted-foreground">Manage your privacy settings and data sharing preferences.</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Access Control</h2>
                    <p className="text-xs text-muted-foreground">Control access to your connected vehicles and features.</p>
                  </div>
                </div>
              </div>
            </div>
          } />
          <Route path="/about" element={
            <div className="container mx-auto max-w-4xl p-5">
              <div className="rounded-lg border bg-card p-5">
                <h1 className="mb-3 text-2xl font-bold">About</h1>
                <p className="mb-5 text-sm text-muted-foreground">Learn more about the Connected Vehicle Platform.</p>
                <div className="flex flex-col gap-3">
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Version</h2>
                    <p className="text-xs text-muted-foreground">Current version: 1.0.0</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Support</h2>
                    <p className="text-xs text-muted-foreground">For assistance, please contact support@connected-car-platform.com</p>
                  </div>
                </div>
              </div>
            </div>
          } />
          <Route path="/profile" element={
            <div className="container mx-auto max-w-4xl p-5">
              <div className="rounded-lg border bg-card p-5">
                <h1 className="mb-3 text-2xl font-bold">User Profile</h1>
                <p className="mb-5 text-sm text-muted-foreground">Manage your personal information and account settings.</p>
                <div className="flex flex-col gap-3">
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Personal Information</h2>
                    <p className="text-xs text-muted-foreground">Update your name, email, and contact details.</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <h2 className="mb-1.5 text-lg font-bold">Preferences</h2>
                    <p className="text-xs text-muted-foreground">Set your account preferences and notification settings.</p>
                  </div>
                </div>
              </div>
            </div>
          } />
        </Routes>
      </MainLayout>
    </div>
  );
}

export default App;
