import React from 'react';
import { useQuery } from 'react-query';
import { Link } from 'react-router-dom';
import {
  ChartBarIcon,
  CurrencyDollarIcon,
  BellIcon,
  ShoppingCartIcon,
  TrendingDownIcon,
  ClockIcon
} from '@heroicons/react/24/outline';
import { format } from 'date-fns';
import api from '../services/api';

function Dashboard() {
  const { data: analytics, isLoading } = useQuery(
    'dashboardAnalytics',
    () => api.getAnalytics(),
    {
      refetchInterval: 60000, // Refresh every minute
    }
  );

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const stats = [
    {
      name: 'Total Products',
      value: analytics?.total_products || 0,
      icon: ShoppingCartIcon,
      color: 'bg-blue-500',
    },
    {
      name: 'Active Tracking',
      value: analytics?.active_products || 0,
      icon: ChartBarIcon,
      color: 'bg-green-500',
    },
    {
      name: 'Alerts Today',
      value: analytics?.alerts_today || 0,
      icon: BellIcon,
      color: 'bg-yellow-500',
    },
    {
      name: 'Total Savings',
      value: `$${(analytics?.total_savings || 0).toFixed(2)}`,
      icon: CurrencyDollarIcon,
      color: 'bg-purple-500',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <Link
          to="/products"
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          Add Product
        </Link>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat) => (
          <div key={stat.name} className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">{stat.name}</p>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
              </div>
              <div className={`${stat.color} p-3 rounded-lg`}>
                <stat.icon className="h-6 w-6 text-white" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Average Price Drop */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Average Price Drop</h2>
          <TrendingDownIcon className="h-6 w-6 text-green-500" />
        </div>
        <div className="flex items-baseline">
          <span className="text-4xl font-bold text-green-500">
            {analytics?.avg_price_drop_percent?.toFixed(1) || 0}%
          </span>
          <span className="ml-2 text-gray-600">across all products</span>
        </div>
      </div>

      {/* Price Drop Opportunities */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-xl font-semibold text-gray-900">Recent Price Drops</h2>
        </div>
        <div className="divide-y divide-gray-200">
          {analytics?.price_drop_opportunities?.length > 0 ? (
            analytics.price_drop_opportunities.map((product) => (
              <div key={product.id} className="p-6 hover:bg-gray-50 transition-colors">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <h3 className="text-lg font-medium text-gray-900 line-clamp-1">
                      {product.title}
                    </h3>
                    <div className="mt-1 flex items-center space-x-4 text-sm text-gray-600">
                      <span>{product.marketplace}</span>
                      <span>•</span>
                      <span className="flex items-center">
                        <ClockIcon className="h-4 w-4 mr-1" />
                        {format(new Date(product.last_checked), 'MMM d, h:mm a')}
                      </span>
                    </div>
                  </div>
                  <div className="text-right ml-4">
                    <p className="text-2xl font-bold text-green-600">
                      ${product.current_price?.toFixed(2)}
                    </p>
                    <p className="text-sm text-gray-500 line-through">
                      ${product.max_price?.toFixed(2)}
                    </p>
                  </div>
                  <Link
                    to={`/products/${product.id}/chart`}
                    className="ml-4 text-blue-600 hover:text-blue-700"
                  >
                    View Details →
                  </Link>
                </div>
              </div>
            ))
          ) : (
            <div className="p-6 text-center text-gray-500">
              No recent price drops
            </div>
          )}
        </div>
      </div>

      {/* Most Tracked Categories */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Popular Categories</h2>
        <div className="space-y-3">
          {analytics?.most_tracked_categories?.map((category) => (
            <div key={category.category} className="flex items-center justify-between">
              <span className="text-gray-700">{category.category}</span>
              <div className="flex items-center">
                <div className="w-32 bg-gray-200 rounded-full h-2 mr-3">
                  <div
                    className="bg-blue-600 h-2 rounded-full"
                    style={{
                      width: `${(category.count / analytics.total_products) * 100}%`,
                    }}
                  ></div>
                </div>
                <span className="text-sm text-gray-600 w-12 text-right">
                  {category.count}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default Dashboard;