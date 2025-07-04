import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from 'react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts';
import { format, subDays } from 'date-fns';
import api from '../services/api';

function PriceChart() {
  const { id } = useParams();
  const [timeRange, setTimeRange] = useState(30); // days

  const { data: product } = useQuery(['product', id], () => api.getProduct(id));
  const { data: priceHistory, isLoading } = useQuery(
    ['priceHistory', id, timeRange],
    () => api.getPriceHistory(id, timeRange),
    {
      enabled: !!id,
    }
  );

  if (isLoading || !product) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  // Process data for the chart
  const chartData = priceHistory?.items?.map((item) => ({
    date: format(new Date(item.scraped_at), 'MMM d'),
    timestamp: new Date(item.scraped_at).getTime(),
    price: item.price,
    inStock: item.in_stock,
  })) || [];

  // Calculate statistics
  const prices = chartData.map(d => d.price).filter(p => p > 0);
  const currentPrice = prices[prices.length - 1] || 0;
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;
  const priceChange = prices.length > 1 ? currentPrice - prices[0] : 0;
  const priceChangePercent = prices.length > 1 ? (priceChange / prices[0]) * 100 : 0;

  const timeRangeOptions = [
    { value: 7, label: '7 Days' },
    { value: 30, label: '30 Days' },
    { value: 90, label: '90 Days' },
    { value: 180, label: '6 Months' },
    { value: 365, label: '1 Year' },
  ];

  return (
    <div className="space-y-6">
      {/* Product Header */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-gray-900 mb-2">{product.title}</h1>
            <div className="flex items-center space-x-4 text-sm text-gray-600">
              <span className="bg-gray-100 px-3 py-1 rounded-full">
                {product.marketplace}
              </span>
              <span>{product.category || 'Uncategorized'}</span>
              <a
                href={product.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-700"
              >
                View on {product.marketplace} →
              </a>
            </div>
          </div>
          {product.image_url && (
            <img
              src={product.image_url}
              alt={product.title}
              className="w-24 h-24 object-cover rounded-lg ml-4"
            />
          )}
        </div>
      </div>

      {/* Price Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Current Price</p>
          <p className="text-2xl font-bold text-gray-900">
            ${currentPrice.toFixed(2)}
          </p>
          <p className={`text-sm ${priceChange < 0 ? 'text-green-600' : 'text-red-600'}`}>
            {priceChange < 0 ? '↓' : '↑'} ${Math.abs(priceChange).toFixed(2)} 
            ({Math.abs(priceChangePercent).toFixed(1)}%)
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Lowest Price</p>
          <p className="text-2xl font-bold text-green-600">
            ${minPrice.toFixed(2)}
          </p>
          <p className="text-sm text-gray-500">Best deal</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Highest Price</p>
          <p className="text-2xl font-bold text-red-600">
            ${maxPrice.toFixed(2)}
          </p>
          <p className="text-sm text-gray-500">Peak price</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Average Price</p>
          <p className="text-2xl font-bold text-gray-900">
            ${avgPrice.toFixed(2)}
          </p>
          <p className="text-sm text-gray-500">Over period</p>
        </div>
      </div>

      {/* Price Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-gray-900">Price History</h2>
          <div className="flex items-center space-x-2">
            {timeRangeOptions.map((option) => (
              <button
                key={option.value}
                onClick={() => setTimeRange(option.value)}
                className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                  timeRange === option.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis 
                dataKey="date"
                tick={{ fontSize: 12 }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 12 }}
                tickLine={false}
                domain={['dataMin - 5', 'dataMax + 5']}
                tickFormatter={(value) => `$${value}`}
              />
              <Tooltip
                formatter={(value) => [`$${value.toFixed(2)}`, 'Price']}
                labelStyle={{ color: '#666' }}
                contentStyle={{
                  backgroundColor: '#fff',
                  border: '1px solid #e5e7eb',
                  borderRadius: '0.5rem',
                  boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
                }}
              />
              <Legend />
              <ReferenceLine
                y={avgPrice}
                stroke="#6b7280"
                strokeDasharray="5 5"
                label={{ value: "Average", position: "right" }}
              />
              {product.target_price && (
                <ReferenceLine
                  y={product.target_price}
                  stroke="#10b981"
                  strokeDasharray="5 5"
                  label={{ value: "Target", position: "right" }}
                />
              )}
              <Line
                type="monotone"
                dataKey="price"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ fill: '#3b82f6', r: 4 }}
                activeDot={{ r: 6 }}
                name="Price"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Stock Status Indicator */}
        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className={`w-3 h-3 rounded-full ${product.in_stock ? 'bg-green-500' : 'bg-red-500'}`}></div>
            <span className="text-sm text-gray-600">
              {product.in_stock ? 'In Stock' : 'Out of Stock'}
            </span>
          </div>
          <span className="text-sm text-gray-500">
            Last updated: {format(new Date(product.last_checked), 'MMM d, yyyy h:mm a')}
          </span>
        </div>
      </div>

      {/* Alert Settings */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Price Alert Settings</h2>
        <div className="flex items-center space-x-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Target Price
            </label>
            <div className="flex items-center space-x-2">
              <span className="text-gray-500">$</span>
              <input
                type="number"
                value={product.target_price || ''}
                placeholder="Set target price"
                className="flex-1 border-gray-300 rounded-lg focus:ring-blue-500 focus:border-blue-500"
                step="0.01"
              />
              <button className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
                Update
              </button>
            </div>
          </div>
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Check Frequency
            </label>
            <select
              value={product.check_interval_hours}
              className="w-full border-gray-300 rounded-lg focus:ring-blue-500 focus:border-blue-500"
            >
              <option value={1}>Every hour</option>
              <option value={4}>Every 4 hours</option>
              <option value={6}>Every 6 hours</option>
              <option value={12}>Every 12 hours</option>
              <option value={24}>Daily</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PriceChart;