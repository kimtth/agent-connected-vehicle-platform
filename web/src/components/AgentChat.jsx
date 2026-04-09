import React, { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Trash2, 
  ChevronDown, 
  Loader2, 
  Lightbulb, 
  Thermometer, 
  Square, 
  Lamp,
  Lock,
  Power,
  Unlock,
  MapPin,
  Battery,
  BatteryCharging,
  Zap,
  Calendar,
  Cloud,
  Car,
  UtensilsCrossed,
  Navigation,
  Wrench,
  AlertTriangle,
  HeartPulse,
  Clock,
  AlertCircle,
  Phone,
  ShieldAlert
} from 'lucide-react';
import { streamAgent } from '../api/chat';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MessageCircle } from 'lucide-react';

// Define available agents with their details
const AVAILABLE_AGENTS = [
  {
    type: "auto-select",
    title: "Auto-Select Agent",
    description: "Automatically choose the best agent based on your query.",
    placeholderText: "E.g., 'What is the status of my vehicle?' or 'Find nearby charging stations'"
  },
  {
    type: "remote-access",
    title: "Remote Access",
    description: "Control vehicle access and remote operations such as door locking, engine start, and syncing personal data.",
    placeholderText: "E.g., 'Lock all doors on my car' or 'Start the engine remotely'"
  },
  {
    type: "safety-emergency",
    title: "Safety & Emergency",
    description: "Handle emergency-related features including collision alerts, eCalls, and theft notifications.",
    placeholderText: "E.g., 'What should I do in case of an accident?' or 'Report my vehicle as stolen'"
  },
  {
    type: "charging-energy",
    title: "Charging & Energy",
    description: "Manage electric vehicle charging operations, energy usage tracking, and charging station information.",
    placeholderText: "E.g., 'Find nearby charging stations' or 'Start charging my vehicle'"
  },
  {
    type: "information-services",
    title: "Information Services",
    description: "Get real-time vehicle-related information such as weather, traffic, and points of interest.",
    placeholderText: "E.g., 'What's the traffic like on my route?' or 'Find restaurants near me'"
  },
  {
    type: "feature-control",
    title: "Vehicle Feature Control",
    description: "Manage in-car features like climate settings, temperature control, and service subscriptions.",
    placeholderText: "E.g., 'Set the temperature to 22 degrees' or 'Show my active subscriptions'"
  },
  {
    type: "diagnostics-battery",
    title: "Diagnostics & Battery",
    description: "Oversee vehicle diagnostics, battery status, and system health reports.",
    placeholderText: "E.g., 'Run a diagnostic check on my car' or 'What's my battery level?'"
  },
  {
    type: "alerts-notifications",
    title: "Alerts & Notifications",
    description: "Manage critical alerts such as speed violations, curfew breaches, and battery warnings.",
    placeholderText: "E.g., 'Set a speed alert for 120 km/h' or 'Show my active alerts'"
  }
];

// Generate a simple unique session ID using timestamp and a random string
const generateSessionId = () =>
  `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

const MarkdownText = ({ children }) => (
  <div className="prose dark:prose-invert prose-xs max-w-none">
    <ReactMarkdown remarkPlugins={[remarkGfm]}>
      {children || ''}
    </ReactMarkdown>
  </div>
);

// Modified component to accept vehicleId prop
const AgentChat = ({ vehicleId }) => {
  const [selectedAgent, setSelectedAgent] = useState(AVAILABLE_AGENTS[0]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [chatAreaHeight, setChatAreaHeight] = useState(0); // dynamic chat history height
  const localStorageWriteTimeout = useRef(null);
  const messagesEndRef = useRef(null);
  const currentAbortRef = useRef(null);
  
  // Generate a session ID if we don't have one
  useEffect(() => {
    if (!sessionId) {
      setSessionId(generateSessionId());
    }
  }, [sessionId]);
    
  // Load chat history from localStorage when selected agent changes
  useEffect(() => {
    if (selectedAgent) {
      const storedHistory = localStorage.getItem(`chat_history_${selectedAgent.type}`);
      if (storedHistory) {
        try {
          setChatHistory(JSON.parse(storedHistory));
        } catch (e) {
          console.error('Error parsing stored chat history:', e);
          setChatHistory([]);
        }
      } else {
        setChatHistory([]);
      }
    }
  }, [selectedAgent]);
  
  // Debounced save chat history to localStorage whenever it changes
  useEffect(() => {
    if (selectedAgent && chatHistory.length > 0) {
      if (localStorageWriteTimeout.current) clearTimeout(localStorageWriteTimeout.current);
      localStorageWriteTimeout.current = setTimeout(() => {
        localStorage.setItem(`chat_history_${selectedAgent.type}`, JSON.stringify(chatHistory));
      }, 500); // 500ms debounce
    }
    return () => {
      if (localStorageWriteTimeout.current) clearTimeout(localStorageWriteTimeout.current);
    };
  }, [chatHistory, selectedAgent]);
  
  // Scroll to bottom of chat whenever history changes
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [chatHistory]);

  // Dynamically size chat history area with debounced resize
  useEffect(() => {
    const OFFSET = 160; // Reduced offset for 120% larger chat area
    let resizeTimeout;
    const calcHeight = () => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        const availableHeight = window.innerHeight - OFFSET;
        setChatAreaHeight(Math.max(400, Math.min(availableHeight, 650)));
      }, 100); // 100ms debounce
    };
    calcHeight();
    window.addEventListener('resize', calcHeight);
    return () => {
      window.removeEventListener('resize', calcHeight);
      if (resizeTimeout) clearTimeout(resizeTimeout);
    };
  }, []);

  const handleQueryChange = (e) => {
    setQuery(e.target.value);
  };

  const clearChatHistory = () => {
    if (selectedAgent) {
      localStorage.removeItem(`chat_history_${selectedAgent.type}`);
      setChatHistory([]);
    }
  };
  
  const submitQuery = async (textParam) => {
    const textToSend = (typeof textParam === 'string' ? textParam : query).trim();
    if (!textToSend || loading) return;

    const userMessage = { type: 'user', text: textToSend, timestamp: new Date().toISOString() };
    setChatHistory(prev => [...prev, userMessage]);
    setLoading(true);
    setQuery('');

    const streamingPlaceholderId = `agent-${Date.now()}`;
    setChatHistory(prev => [...prev, {
      type: 'agent',
      text: '',
      agentType: selectedAgent.type,
      agentTitle: selectedAgent.title,
      streaming: true,
      id: streamingPlaceholderId,
      timestamp: new Date().toISOString()
    }]);

    const combined = [...chatHistory, userMessage];
    const lastItems = combined.slice(-10).map(m => ({
      role: m.type === 'user' ? 'user' : (m.type === 'agent' ? 'assistant' : m.type),
      content: m.text
    }));

    const sid = sessionId || generateSessionId();
    if (!sessionId) setSessionId(sid);

    const payload = {
      query: textToSend,
      context: {
        agentType: selectedAgent.type,
        conversationHistory: lastItems,
        vehicleId: vehicleId,
        timestamp: new Date().toISOString()
      },
      sessionId: sid
    };

    // abort previous stream if any
    if (currentAbortRef.current) {
      currentAbortRef.current();
      currentAbortRef.current = null;
    }
    try {
      const abortStream = streamAgent(payload, {
        onChunk: (fullText, chunk) => {
          if (fullText === 'Processing your request...' && !chunk.complete) {
            return; // suppress placeholder text
          }
          setChatHistory(prev => prev.map(m =>
            m.id === streamingPlaceholderId
              ? {
                  ...m,
                  text: fullText,
                  pluginsUsed: chunk.pluginsUsed || m.pluginsUsed
                }
              : m
          ));
        },
        onComplete: (finalText, chunk) => {
          setChatHistory(prev => prev.map(m =>
            m.id === streamingPlaceholderId
              ? {
                  ...m,
                  text: finalText || m.text,
                  streaming: false,
                  pluginsUsed: chunk?.pluginsUsed || m.pluginsUsed
                }
              : m
          ));
          currentAbortRef.current = null;
        },
        onError: () => {
          setChatHistory(prev => prev.map(m =>
            m.id === streamingPlaceholderId
              ? {
                  ...m,
                  text: (m.text && m.text.length)
                    ? m.text + '\n\n[Streaming interrupted]'
                    : 'Streaming failed. Please retry.',
                  streaming: false,
                  error: true
                }
              : m
          ));
          currentAbortRef.current = null;
        }
      });
      currentAbortRef.current = abortStream;
    } catch (e) {
      console.error('stream start error', e);
      setChatHistory(prev => prev.map(m =>
        m.id === streamingPlaceholderId
          ? { ...m, text: 'Unable to start stream.', streaming: false, error: true }
          : m
      ));
    } finally {
      setLoading(false);
    }
    return currentAbortRef.current;
  };

  const handleQuickAction = (message) => {
    submitQuery(message);
  };

  // Handle Enter key press
  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitQuery();
    }
  };

  const quickActions = useMemo(() => [
    {
      category: 'features',
      title: 'Vehicle Features',
      actions: [
        { icon: Lightbulb, text: 'Turn on headlights', message: 'Please turn on the headlights' },
        { icon: Thermometer, text: 'Set climate to 22°C', message: 'Set the climate control to 22 degrees' },
        { icon: Square, text: 'Roll up all windows', message: 'Please roll up all the windows' },
        { icon: Lamp, text: 'Turn on interior lights', message: 'Turn on the interior lights' }
      ]
    },
    {
      category: 'remote',
      title: 'Remote Access',
      actions: [
        { icon: Lock, text: 'Lock doors', message: 'Lock all the doors' },
        { icon: Power, text: 'Start engine', message: 'Start the engine remotely' },
        { icon: Unlock, text: 'Unlock vehicle', message: 'Unlock the vehicle doors' },
        { icon: MapPin, text: 'Locate vehicle', message: 'Help me find my vehicle with horn and lights' }
      ]
    },
    {
      category: 'charging',
      title: 'Charging & Energy',
      actions: [
        { icon: Zap, text: 'Find charging stations', message: 'Find nearby charging stations' },
        { icon: Battery, text: 'Check battery status', message: 'What is my current battery level and range?' },
        { icon: BatteryCharging, text: 'Start charging', message: 'Start charging the vehicle' },
        { icon: Calendar, text: 'Set charging schedule', message: 'Set up a charging schedule for overnight' }
      ]
    },
    {
      category: 'info',
      title: 'Information Services',
      actions: [
        { icon: Cloud, text: 'Weather update', message: 'What is the current weather?' },
        { icon: Car, text: 'Traffic conditions', message: 'Check traffic conditions on my route' },
        { icon: UtensilsCrossed, text: 'Find restaurants', message: 'Find restaurants near my location' },
        { icon: Navigation, text: 'Navigation help', message: 'Help me navigate to the nearest gas station' }
      ]
    },
    {
      category: 'diagnostics',
      title: 'Diagnostics & Alerts',
      actions: [
        { icon: Wrench, text: 'Vehicle diagnostics', message: 'Run a full vehicle diagnostic check' },
        { icon: AlertTriangle, text: 'Check alerts', message: 'Show me any active alerts or warnings' },
        { icon: HeartPulse, text: 'Battery health', message: 'Check my vehicle battery health status' },
        { icon: Clock, text: 'Maintenance status', message: 'When is my next scheduled maintenance?' }
      ]
    },
    {
      category: 'emergency',
      title: 'Emergency & Safety',
      actions: [
        { icon: AlertCircle, text: 'Emergency SOS', message: 'EMERGENCY SOS - I need immediate help' },
        { icon: ShieldAlert, text: 'Report collision', message: 'I need to report a collision' },
        { icon: Phone, text: 'Call emergency services', message: 'I need to call emergency services' },
        { icon: ShieldAlert, text: 'Report theft', message: 'I need to report my vehicle as stolen' }
      ]
    }
  ], []);

  const renderedChatHistory = useMemo(() => chatHistory.map((message, index) => (
    <div key={index} className="flex flex-col">
      <div className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'} mb-3`}>
        <div className={`max-w-[80%] rounded-lg p-3 text-xs leading-relaxed ${
          message.type === 'user' 
            ? 'bg-primary text-primary-foreground' 
            : message.type === 'error' 
            ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' 
            : 'bg-muted'
        }`}>
          {message.type !== 'user' && (
            <p className="text-[11px] text-muted-foreground font-medium mb-1.5">
              {message.type === 'agent' ? message.agentTitle : 'System Message'}
            </p>
          )}
          {message.type === 'agent' ? (
            <MarkdownText>{message.text}</MarkdownText>
          ) : (
            <p className="text-xs whitespace-pre-wrap">
              {message.text}
            </p>
          )}
          {message.data && (
            <div className="mt-4 p-3 bg-muted/50 rounded-md">
              <p className="text-xs text-muted-foreground mb-2">Additional Data:</p>
              <pre className="text-xs overflow-auto m-0">
                {JSON.stringify(message.data, null, 2)}
              </pre>
            </div>
          )}
          {message.streaming && (
            <div className="flex items-center gap-1.5 mt-2">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-[10px] text-muted-foreground">typing</span>
            </div>
          )}
        </div>
      </div>
      {index < chatHistory.length - 1 && <div className="h-px bg-border my-2" />}
    </div>
  )), [chatHistory]);

  return (
    <div className="flex flex-col h-full p-5" style={{ minHeight: '520px' }}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="text-xl font-semibold">Agent Chat</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {vehicleId ? `Vehicle: ${vehicleId.substring(0, 8)}...` : 'No vehicle selected'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
            Connected
          </span>
        </div>
      </div>
      
      <div className="flex gap-1.5 items-center mb-2">
        <div className="relative flex-1">
          <select 
            value={selectedAgent.type}
            onChange={(e) => {
              const agent = AVAILABLE_AGENTS.find(a => a.type === e.target.value);
              setSelectedAgent(agent);
            }}
            className="w-full px-2.5 py-1.5 text-sm border border-input rounded-md bg-background appearance-none pr-8"
          >
            {AVAILABLE_AGENTS.map((agent) => (
              <option key={agent.type} value={agent.type}>
                {agent.title}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 pointer-events-none" />
        </div>
        
        <button 
          className="p-1.5 rounded-md bg-red-100 text-red-600 hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          onClick={clearChatHistory}
          disabled={chatHistory.length === 0}
          title="Clear chat history"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      
      <div className="flex flex-1 flex-col gap-2.5 min-h-0 lg:flex-row">
        <div className="flex flex-col flex-1 min-h-0 min-w-0">
          <div 
            className="flex-1 min-h-0 overflow-y-auto border rounded-lg bg-card mb-2.5" 
            style={{ maxHeight: chatAreaHeight || undefined, minHeight: '460px' }}
          >
            <div className="flex flex-col gap-2.5 p-3">
              {chatHistory.length > 0 ? (
                renderedChatHistory
              ) : (
                <div className="flex flex-col items-center justify-center h-full py-12 px-4">
                  <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                    <MessageCircle className="h-8 w-8 text-primary/60" />
                  </div>
                  <p className="text-sm font-medium text-foreground/80 mb-1">
                    Start a conversation
                  </p>
                  <p className="text-xs text-muted-foreground text-center max-w-[280px]">
                    Ask the {selectedAgent.title} anything about your vehicle, or try a quick action from the sidebar.
                  </p>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>
          
          <div className="flex gap-1.5">
            <textarea
              placeholder={selectedAgent.placeholderText}
              value={query}
              onChange={(e) => handleQueryChange(e)}
              onKeyDown={handleKeyPress}
              disabled={loading}
              rows={2}
              className="flex-1 px-2.5 py-1.5 text-sm border border-input rounded-md bg-background resize-none disabled:opacity-50"
            />
            <button 
              onClick={submitQuery}
              disabled={loading || !query.trim()}
              className="min-w-[100px] px-3 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center justify-center gap-1.5"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Send'}
            </button>
          </div>
        </div>

        <div 
          className="w-full flex-shrink-0 rounded-lg border bg-card p-4 flex flex-col mt-2 lg:w-72 lg:mt-0" 
          style={{ height: chatAreaHeight ? `${chatAreaHeight + 60}px` : undefined, minHeight: '520px' }}
        >
          <h2 className="text-lg font-bold mb-3">Quick Actions</h2>
          <div className="overflow-y-auto flex-1">
            {quickActions.map((group) => (
              <div key={group.category} className="mb-4">
                <p className="text-xs font-medium text-muted-foreground mb-1.5">
                  {group.title}
                </p>
                <div className="grid grid-cols-2 gap-1.5">
                  {group.actions.map((action, index) => {
                    const Icon = action.icon;
                    return (
                      <button
                        key={index}
                        className={`px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 justify-center ${
                          group.category === 'features' ? 'bg-blue-100 text-blue-800 hover:bg-blue-200 dark:bg-blue-900 dark:text-blue-200' :
                          group.category === 'remote' ? 'bg-cyan-100 text-cyan-800 hover:bg-cyan-200 dark:bg-cyan-900 dark:text-cyan-200' :
                          group.category === 'charging' ? 'bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900 dark:text-green-200' :
                          group.category === 'info' ? 'bg-orange-100 text-orange-800 hover:bg-orange-200 dark:bg-orange-900 dark:text-orange-200' :
                          group.category === 'diagnostics' ? 'bg-purple-100 text-purple-800 hover:bg-purple-200 dark:bg-purple-900 dark:text-purple-200' :
                          'bg-red-100 text-red-800 hover:bg-red-200 dark:bg-red-900 dark:text-red-200'
                        }`}
                        onClick={() => handleQuickAction(action.message)}
                        disabled={loading}
                      >
                        <Icon className="h-3 w-3 flex-shrink-0" />
                        <span className="truncate">{action.text}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AgentChat;

