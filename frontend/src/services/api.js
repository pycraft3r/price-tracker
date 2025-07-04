import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

// Create axios instance
const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth API
const auth = {
  login: (credentials) => api.post('/auth/login', credentials),
  register: (userData) => api.post('/auth/register', userData),
  getProfile: () => api.get('/auth/profile'),
  updateProfile: (data) => api.put('/auth/profile', data),
};

// Products API
const products = {
  getProducts: (params) => api.get('/products', { params }).then(res => res.data),
  getProduct: (id) => api.get(`/products/${id}`).then(res => res.data),
  createProduct: (data) => api.post('/products', data).then(res => res.data),
  updateProduct: (id, data) => api.patch(`/products/${id}`, data).then(res => res.data),
  deleteProduct: (id) => api.delete(`/products/${id}`),
  getPriceHistory: (id, days = 30) => 
    api.get(`/products/${id}/prices`, { params: { days } }).then(res => res.data),
  bulkCreateProducts: (data) => api.post('/products/bulk', data).then(res => res.data),
};

// Alerts API
const alerts = {
  getAlerts: (params) => api.get('/alerts', { params }).then(res => res.data),
  markAlertRead: (id) => api.patch(`/alerts/${id}/read`),
  deleteAlert: (id) => api.delete(`/alerts/${id}`),
  getAlertSettings: () => api.get('/alerts/settings').then(res => res.data),
  updateAlertSettings: (data) => api.put('/alerts/settings', data),
};

// Analytics API
const analytics = {
  getAnalytics: () => api.get('/analytics/dashboard').then(res => res.data),
  getProductAnalytics: (id) => api.get(`/analytics/product/${id}`).then(res => res.data),
  getReports: (params) => api.get('/analytics/reports', { params }).then(res => res.data),
};

// Export all API methods
export default {
  // Auth
  login: auth.login,
  register: auth.register,
  getProfile: auth.getProfile,
  updateProfile: auth.updateProfile,
  
  // Products
  getProducts: products.getProducts,
  getProduct: products.getProduct,
  createProduct: products.createProduct,
  updateProduct: products.updateProduct,
  deleteProduct: products.deleteProduct,
  getPriceHistory: products.getPriceHistory,
  bulkCreateProducts: products.bulkCreateProducts,
  
  // Alerts
  getAlerts: alerts.getAlerts,
  markAlertRead: alerts.markAlertRead,
  deleteAlert: alerts.deleteAlert,
  getAlertSettings: alerts.getAlertSettings,
  updateAlertSettings: alerts.updateAlertSettings,
  
  // Analytics
  getAnalytics: analytics.getAnalytics,
  getProductAnalytics: analytics.getProductAnalytics,
  getReports: analytics.getReports,
  
  // Raw axios instance for custom requests
  axios: api,
};