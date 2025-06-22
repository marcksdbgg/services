import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';
import './App.css';

const API_GATEWAY_URL = process.env.REACT_APP_API_GATEWAY_URL;

function App() {
  const [files, setFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback(acceptedFiles => {
    const newFiles = acceptedFiles.map(file => Object.assign(file, {
      id: `file_${Date.now()}_${Math.random()}`,
      status: 'queued',
      error: null,
      response: null,
    }));
    setFiles(prevFiles => [...prevFiles, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    // Tipos permitidos: PDF, DOCX, TXT, HTML, Markdown
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'text/html': ['.html', '.htm'],
    },
  });

  const handleUpload = async () => {
    if (!API_GATEWAY_URL) {
      alert("Error de configuración: La URL del API Gateway no está definida. Por favor, configura REACT_APP_API_GATEWAY_URL en tu archivo .env.");
      return;
    }

    const filesToUpload = files.filter(f => f.status === 'queued');
    if (filesToUpload.length === 0) return;

    setIsUploading(true);

    const uploadPromises = filesToUpload.map(file => {
      setFiles(current => current.map(f => f.id === file.id ? { ...f, status: 'uploading' } : f));
      
      const formData = new FormData();
      formData.append('file', file);

      return axios.post(`${API_GATEWAY_URL}/api/v1/ingest/upload`, formData, {
        headers: {
          'X-Company-ID': 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
        },
      })
      .then(response => {
        setFiles(current => current.map(f =>
          f.id === file.id ? { ...f, status: 'success', response: response.data } : f
        ));
      })
      .catch(error => {
        const errorMessage = error.response?.data?.detail || error.message || 'Error desconocido';
        setFiles(current => current.map(f =>
          f.id === file.id ? { ...f, status: 'error', error: errorMessage } : f
        ));
      });
    });

    await Promise.all(uploadPromises);
    setIsUploading(false);
  };

  const queuedFilesCount = files.filter(f => f.status === 'queued').length;
  const humanFileSize = (size) => {
    if (size === 0) return '0 B';
    const i = Math.floor(Math.log(size) / Math.log(1024));
    return `${(size / Math.pow(1024, i)).toFixed(2)} ${['B', 'KB', 'MB', 'GB'][i]}`;
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Ateneo - Carga de Documentos</h1>
        <p>Arrastra archivos aquí para iniciar el pipeline de datos en Kafka y Flink.</p>
      </header>

      <div className="upload-section">
        <div {...getRootProps({ className: `dropzone ${isDragActive ? 'dropzone-active' : ''} ${isDragReject ? 'dropzone-reject' : ''}` })}>
          <input {...getInputProps()} />
          {isDragReject ? <p>Tipo de archivo no soportado.</p> : isDragActive ? <p>¡Suelta los archivos aquí!</p> : <p>Arrastra tus archivos o haz clic para seleccionar.</p>}
        </div>
        <button className="upload-button" onClick={handleUpload} disabled={isUploading || queuedFilesCount === 0}>
          {isUploading ? 'Subiendo...' : `Subir ${queuedFilesCount} Archivo(s)`}
        </button>
      </div>
      
      {files.length > 0 && (
        <div className="file-list-container">
          <h2>Archivos en esta sesión</h2>
          <ul className="file-list">
            {[...files].reverse().map(file => (
              <li key={file.id} className="file-item">
                <div className="file-info">
                  <div className="file-name" title={file.name}>{file.name}</div>
                  <div className="file-details">{humanFileSize(file.size)}</div>
                  {file.status === 'error' && <div className="error-message">{file.error}</div>}
                </div>
                <span className={`file-status status-${file.status}`}>
                  {file.status === 'error' ? 'Error' : file.status === 'success' ? 'Enviado' : file.status === 'uploading' ? 'Subiendo' : 'En Cola'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default App;