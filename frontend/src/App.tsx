import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import PublicPage from './pages/PublicPage';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import RolePage from './pages/RolePage';
import { ToastProvider } from './components/UI';

export default function App(){
  const [ready,setReady]=useState(false);
  useEffect(()=>{const t=setTimeout(()=>setReady(true),500); return()=>clearTimeout(t)},[]);
  if(!ready) return <div className="boot"><div className="tooth">●</div><div className="skeleton wide"/><div className="skeleton"/></div>;
  return <ToastProvider><Routes>
    <Route path="/" element={<PublicPage section="home"/>}/><Route path="/services" element={<PublicPage section="services"/>}/><Route path="/doctors" element={<PublicPage section="doctors"/>}/><Route path="/resources" element={<PublicPage section="resources"/>}/><Route path="/contact" element={<PublicPage section="contact"/>}/><Route path="/login" element={<LoginPage/>}/>
    <Route path="/admin" element={<Dashboard role="admin"/>}/><Route path="/admin/:section" element={<RolePage role="admin"/>}/>
    <Route path="/receptionist" element={<Dashboard role="receptionist"/>}/><Route path="/receptionist/:section" element={<RolePage role="receptionist"/>}/>
    <Route path="/doctor" element={<Dashboard role="doctor"/>}/><Route path="/doctor/:section" element={<RolePage role="doctor"/>}/>
    <Route path="*" element={<Navigate to="/"/>}/>
  </Routes></ToastProvider>
}
