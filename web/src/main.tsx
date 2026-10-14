import {ToastHost} from './Toast';
import ReactDOM from 'react-dom/client';
import App from './App';
import './style.css';
import './workspace.css';
import './studio.css';
ReactDOM.createRoot(document.getElementById('root')!).render(<><App/><ToastHost/></>);
