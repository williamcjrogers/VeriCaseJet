import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { CorrespondenceView } from './views/CorrespondenceView';
import { EvidenceView } from './views/EvidenceView';
import { TimelineView } from './views/TimelineView';
import { LoginView } from './views/LoginView';
import './App.css';

function App() {
  return (
    <Router>
      <Routes>
        {/* Default route is Login */}
        <Route path="/" element={<LoginView />} />
        <Route path="/login" element={<LoginView />} />

        {/* Protected Routes */}
        <Route path="/correspondence" element={<CorrespondenceView />} />
        <Route path="/evidence" element={<EvidenceView />} />
        <Route path="/timeline" element={<TimelineView />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
