#!/usr/bin/env python3

from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import os
import glob
import time
import threading
import json
from collections import deque
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests

class ThermalMonitor:
    def __init__(self):
        self.thermal_zones = []
        self.fan_sensors = []
        self.temperature_history = deque(maxlen=100)
        self.current_temps = {}
        self.current_fans = {}
        self.stats = {
            'avg_temp': 0,
            'max_temp': 0,
            'min_temp': 100,
            'cpu_temp': 0
        }
        self.discover_thermal_zones()
        self.discover_fan_sensors()
        self.start_monitoring()
    
    def discover_thermal_zones(self):
        """Discover available thermal zones"""
        thermal_pattern = '/sys/class/thermal/thermal_zone*/temp'
        temp_files = glob.glob(thermal_pattern)
        
        for temp_file in temp_files:
            zone_path = os.path.dirname(temp_file)
            zone_num = temp_file.split('thermal_zone')[1].split('/')[0]
            
            # Try to read the thermal zone type
            type_file = os.path.join(zone_path, 'type')
            zone_type = 'unknown'
            try:
                with open(type_file, 'r') as f:
                    zone_type = f.read().strip()
            except:
                pass
            
            self.thermal_zones.append({
                'id': zone_num,
                'path': temp_file,
                'type': zone_type,
                'name': f"Zone {zone_num} ({zone_type})"
            })
        
        print(f"Discovered {len(self.thermal_zones)} thermal zones:")
        for zone in self.thermal_zones:
            print(f"  - {zone['name']}: {zone['path']}")
    
    def discover_fan_sensors(self):
        """Discover available fan sensors"""
        fan_sensors = []
        
        # Search through all hwmon directories
        hwmon_pattern = '/sys/class/hwmon/hwmon*'
        hwmon_dirs = glob.glob(hwmon_pattern)
        
        for hwmon_dir in hwmon_dirs:
            try:
                # Get the device name
                name_file = os.path.join(hwmon_dir, 'name')
                device_name = 'unknown'
                try:
                    with open(name_file, 'r') as f:
                        device_name = f.read().strip()
                except:
                    pass
                
                # Look for fan input files
                fan_pattern = os.path.join(hwmon_dir, 'fan*_input')
                fan_files = glob.glob(fan_pattern)
                
                for fan_file in fan_files:
                    fan_num = fan_file.split('fan')[1].split('_')[0]
                    
                    # Try to read the fan label
                    label_file = os.path.join(hwmon_dir, f'fan{fan_num}_label')
                    fan_label = f'Fan {fan_num}'
                    try:
                        with open(label_file, 'r') as f:
                            fan_label = f.read().strip()
                    except:
                        pass
                    
                    # Test if we can read the fan speed
                    try:
                        with open(fan_file, 'r') as f:
                            speed = int(f.read().strip())
                            if speed >= 0:  # Valid fan speed
                                fan_sensors.append({
                                    'id': f"{device_name}_{fan_num}",
                                    'path': fan_file,
                                    'label': fan_label,
                                    'device': device_name,
                                    'fan_num': fan_num,
                                    'name': f"{device_name} - {fan_label}"
                                })
                    except:
                        pass
                        
            except Exception as e:
                print(f"Error scanning {hwmon_dir}: {e}")
        
        self.fan_sensors = fan_sensors
        print(f"Discovered {len(self.fan_sensors)} fan sensors:")
        for fan in self.fan_sensors:
            print(f"  - {fan['name']}: {fan['path']}")
    
    def read_fan_speed(self, fan_file):
        """Read fan speed from a fan sensor file"""
        try:
            with open(fan_file, 'r') as f:
                # Fan speed is in RPM
                speed_rpm = int(f.read().strip())
                return speed_rpm
        except Exception as e:
            print(f"Error reading {fan_file}: {e}")
            return None
    
    def read_temperature(self, temp_file):
        """Read temperature from a thermal zone file"""
        try:
            with open(temp_file, 'r') as f:
                # Temperature is in millidegrees Celsius
                temp_millidegrees = int(f.read().strip())
                return temp_millidegrees / 1000.0
        except Exception as e:
            print(f"Error reading {temp_file}: {e}")
            return None
    
    def get_cpu_temperature(self):
        """Get the primary CPU temperature"""
        # Priority order for CPU temperature zones
        cpu_types = ['x86_pkg_temp', 'cpu_thermal', 'coretemp', 'acpi-0']
        
        # First, try to find a zone with CPU-related type
        for cpu_type in cpu_types:
            for zone in self.thermal_zones:
                if cpu_type.lower() in zone['type'].lower():
                    temp = self.read_temperature(zone['path'])
                    if temp is not None:
                        return temp
        
        # If no specific CPU zone found, use the first available zone
        for zone in self.thermal_zones:
            temp = self.read_temperature(zone['path'])
            if temp is not None:
                return temp
        
        return None
    
    def update_temperatures(self):
        """Update all temperature readings"""
        temps = {}
        valid_temps = []
        
        for zone in self.thermal_zones:
            temp = self.read_temperature(zone['path'])
            if temp is not None:
                temps[zone['id']] = {
                    'temperature': temp,
                    'type': zone['type'],
                    'name': zone['name']
                }
                valid_temps.append(temp)
        
        self.current_temps = temps
        
        # Update statistics
        if valid_temps:
            cpu_temp = self.get_cpu_temperature()
            if cpu_temp is not None:
                self.stats['cpu_temp'] = cpu_temp
                self.temperature_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'temperature': cpu_temp
                })
                
                # Calculate statistics from history
                recent_temps = [entry['temperature'] for entry in list(self.temperature_history)[-20:]]
                if recent_temps:
                    self.stats['avg_temp'] = sum(recent_temps) / len(recent_temps)
                    self.stats['max_temp'] = max(recent_temps)
                    self.stats['min_temp'] = min(recent_temps)
    
    def update_fans(self):
        """Update all fan speed readings"""
        fans = {}
        
        for fan in self.fan_sensors:
            speed = self.read_fan_speed(fan['path'])
            if speed is not None:
                fans[fan['id']] = {
                    'speed': speed,
                    'label': fan['label'],
                    'device': fan['device'],
                    'name': fan['name']
                }
        
        self.current_fans = fans
    
    def start_monitoring(self):
        """Start background temperature and fan monitoring"""
        def monitor_loop():
            while True:
                self.update_temperatures()
                self.update_fans()
                time.sleep(1)  # Update every second
        
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()

# Initialize thermal monitor
thermal_monitor = ThermalMonitor()

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/temperature')
def get_temperature():
    """Get current CPU temperature"""
    return jsonify({
        'temperature': thermal_monitor.stats['cpu_temp'],
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/all-temperatures')
def get_all_temperatures():
    """Get temperatures from all thermal zones"""
    return jsonify({
        'zones': thermal_monitor.current_temps,
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/stats')
def get_stats():
    """Get temperature statistics"""
    return jsonify({
        'stats': thermal_monitor.stats,
        'history_count': len(thermal_monitor.temperature_history),
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/history')
def get_history():
    """Get temperature history"""
    return jsonify({
        'history': list(thermal_monitor.temperature_history),
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/zones')
def get_zones():
    """Get information about available thermal zones"""
    return jsonify({
        'zones': thermal_monitor.thermal_zones,
        'count': len(thermal_monitor.thermal_zones),
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/fans')
def get_fans():
    """Get current fan speeds"""
    return jsonify({
        'fans': thermal_monitor.current_fans,
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/api/fan-sensors')
def get_fan_sensors():
    """Get information about available fan sensors"""
    return jsonify({
        'sensors': thermal_monitor.fan_sensors,
        'count': len(thermal_monitor.fan_sensors),
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })

# Claude.ai-inspired HTML Template with modern design
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CPU Temperature Monitor</title>
    <style>
        :root {
            --claude-bg: #f8f9fa;
            --claude-sidebar: #ffffff;
            --claude-card: #ffffff;
            --claude-border: #e5e7eb;
            --claude-text-primary: #1a1a1a;
            --claude-text-secondary: #666666;
            --claude-accent: #10a37f;
            --claude-accent-light: #e6f6f1;
            --claude-warning: #f59e0b;
            --claude-danger: #ef4444;
            --claude-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            --claude-radius: 8px;
            --claude-radius-sm: 4px;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background-color: var(--claude-bg);
            color: var(--claude-text-primary);
            line-height: 1.5;
            min-height: 100vh;
            padding: 0;
            margin: 0;
        }

        .app-container {
            display: flex;
            min-height: 100vh;
        }

        .sidebar {
            width: 280px;
            background-color: var(--claude-sidebar);
            border-right: 1px solid var(--claude-border);
            padding: 20px;
            height: 100vh;
            position: sticky;
            top: 0;
            overflow-y: auto;
        }

        .main-content {
            flex: 1;
            padding: 24px;
            max-width: 1200px;
            margin: 0 auto;
        }

        .header {
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--claude-border);
        }

        .title {
            font-size: 20px;
            font-weight: 600;
            color: var(--claude-text-primary);
            margin-bottom: 4px;
        }

        .subtitle {
            font-size: 14px;
            color: var(--claude-text-secondary);
        }

        .card {
            background-color: var(--claude-card);
            border-radius: var(--claude-radius);
            border: 1px solid var(--claude-border);
            box-shadow: var(--claude-shadow);
            padding: 20px;
            margin-bottom: 20px;
        }

        .temp-display {
            text-align: center;
            margin-bottom: 24px;
        }

        .temp-value {
            font-size: 56px;
            font-weight: 600;
            color: var(--claude-accent);
            line-height: 1;
            margin-bottom: 8px;
            transition: color 0.3s ease;
        }

        .temp-unit {
            font-size: 16px;
            color: var(--claude-text-secondary);
            font-weight: 500;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            margin-top: 12px;
            background-color: var(--claude-accent-light);
            color: var(--claude-accent);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--claude-accent);
            animation: pulse 2s infinite;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }

        .stat-card {
            background-color: var(--claude-card);
            border-radius: var(--claude-radius-sm);
            border: 1px solid var(--claude-border);
            padding: 12px;
        }

        .stat-label {
            font-size: 12px;
            color: var(--claude-text-secondary);
            margin-bottom: 4px;
            font-weight: 500;
        }

        .stat-value {
            font-size: 18px;
            font-weight: 600;
            color: var(--claude-text-primary);
        }

        .chart-container {
            height: 280px;
            width: 100%;
            position: relative;
        }

        .chart-canvas {
            width: 100%;
            height: 100%;
        }

        .zones-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--claude-text-primary);
            margin-bottom: 12px;
        }

        .zone-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--claude-border);
            font-size: 13px;
        }

        .zone-item:last-child {
            border-bottom: none;
        }

        .zone-name {
            color: var(--claude-text-secondary);
        }

        .zone-temp {
            font-weight: 600;
            color: var(--claude-text-primary);
        }

        .error {
            background-color: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: var(--claude-danger);
            padding: 12px;
            border-radius: var(--claude-radius-sm);
            font-size: 13px;
            margin-top: 16px;
            display: none;
        }

        /* Temperature status colors */
        .temp-normal { color: var(--claude-accent); }
        .temp-warm { color: var(--claude-warning); }
        .temp-hot { color: var(--claude-danger); }

        .status-normal {
            background-color: var(--claude-accent-light);
            color: var(--claude-accent);
        }

        .status-warm {
            background-color: rgba(245, 158, 11, 0.1);
            color: var(--claude-warning);
        }

        .status-hot {
            background-color: rgba(239, 68, 68, 0.1);
            color: var(--claude-danger);
        }

        @keyframes pulse {
            0%, 100% { 
                opacity: 1;
            }
            50% { 
                opacity: 0.5;
            }
        }

        /* Tooltip for chart */
        .tooltip {
            position: absolute;
            background-color: var(--claude-card);
            border: 1px solid var(--claude-border);
            border-radius: var(--claude-radius-sm);
            padding: 8px 12px;
            font-size: 13px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
            box-shadow: var(--claude-shadow);
            z-index: 100;
        }

        .tooltip-value {
            font-weight: 600;
            color: var(--claude-accent);
        }

        .tooltip-time {
            color: var(--claude-text-secondary);
            font-size: 12px;
        }

        @media (max-width: 768px) {
            .app-container {
                flex-direction: column;
            }

            .sidebar {
                width: 100%;
                height: auto;
                position: relative;
                border-right: none;
                border-bottom: 1px solid var(--claude-border);
            }

            .main-content {
                padding: 16px;
            }

            .temp-value {
                font-size: 48px;
            }

            .chart-container {
                height: 220px;
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="sidebar">
            <div class="header">
                <h1 class="title">CPU Temperature Monitor</h1>
                <p class="subtitle">Real-time system monitoring</p>
            </div>
            
            <div class="card">
                <div class="temp-display">
                    <div class="temp-value" id="tempValue">--</div>
                    <div class="temp-unit">°C</div>
                    <div class="status-badge" id="statusBadge">
                        <div class="status-dot"></div>
                        <span id="statusText">Connecting...</span>
                    </div>
                </div>

                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">Average</div>
                        <div class="stat-value" id="avgTemp">--°C</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Peak</div>
                        <div class="stat-value" id="maxTemp">--°C</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Minimum</div>
                        <div class="stat-value" id="minTemp">--°C</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Zones</div>
                        <div class="stat-value" id="zoneCount">--</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="zones-title">Thermal Zones</div>
                <div id="zonesList"></div>
            </div>

            <div class="card">
                <div class="zones-title">Fan Speeds</div>
                <div id="fansList"></div>
            </div>

            <div id="errorDisplay" class="error"></div>
        </div>

        <div class="main-content">
            <div class="card">
                <div class="header">
                    <h2 class="title">Temperature History</h2>
                </div>
                <div class="chart-container">
                    <canvas class="chart-canvas" id="temperatureChart"></canvas>
                    <div id="chartTooltip" class="tooltip">
                        <div class="tooltip-value" id="tooltipValue">--°C</div>
                        <div class="tooltip-time" id="tooltipTime">--</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        class CPUTempMonitor {
            constructor() {
                this.tempHistory = [];
                this.maxHistory = 60; // Show last 60 seconds
                this.apiBase = '';
                this.chart = null;
                this.minTemp = 20;
                this.maxTemp = 90;
                
                this.initChart();
                this.startMonitoring();
            }

            async readTemperature() {
                try {
                    const response = await fetch(`${this.apiBase}/api/temperature`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    const data = await response.json();
                    return data.temperature;
                } catch (error) {
                    console.error('Error reading temperature:', error);
                    this.showError(`Failed to read temperature: ${error.message}`);
                    return null;
                }
            }

            async readStats() {
                try {
                    const response = await fetch(`${this.apiBase}/api/stats`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    const data = await response.json();
                    return data.stats;
                } catch (error) {
                    console.error('Error reading stats:', error);
                    return null;
                }
            }

            async readAllTemperatures() {
                try {
                    const response = await fetch(`${this.apiBase}/api/all-temperatures`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    const data = await response.json();
                    return data.zones;
                } catch (error) {
                    console.error('Error reading all temperatures:', error);
                    return null;
                }
            }

            async readFanSpeeds() {
                try {
                    const response = await fetch(`${this.apiBase}/api/fans`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    const data = await response.json();
                    return data.fans;
                } catch (error) {
                    console.error('Error reading fan speeds:', error);
                    return null;
                }
            }

            showError(message) {
                const errorDisplay = document.getElementById('errorDisplay');
                errorDisplay.textContent = message;
                errorDisplay.style.display = 'block';
                setTimeout(() => {
                    errorDisplay.style.display = 'none';
                }, 5000);
            }

            initChart() {
                const ctx = document.getElementById('temperatureChart').getContext('2d');
                
                // Destroy existing chart if it exists
                if (this.chart) {
                    this.chart.destroy();
                }
                
                this.chart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: Array(this.maxHistory).fill(''),
                        datasets: [{
                            label: 'CPU Temperature',
                            data: Array(this.maxHistory).fill(null),
                            borderColor: '#10a37f',
                            backgroundColor: 'rgba(16, 163, 127, 0.1)',
                            borderWidth: 2,
                            pointRadius: 0,
                            pointHoverRadius: 5,
                            fill: true,
                            tension: 0.4,
                            cubicInterpolationMode: 'monotone'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: {
                                min: this.minTemp,
                                max: this.maxTemp,
                                grid: {
                                    color: 'rgba(0, 0, 0, 0.05)'
                                },
                                ticks: {
                                    callback: function(value) {
                                        return value + '°C';
                                    }
                                }
                            },
                            x: {
                                grid: {
                                    display: false
                                },
                                ticks: {
                                    callback: function(value, index, values) {
                                        if (index === 0) return '60s ago';
                                        if (index === values.length - 1) return 'Now';
                                        if (index % 15 === 0) return (values.length - index) + 's';
                                        return '';
                                    }
                                }
                            }
                        },
                        plugins: {
                            legend: {
                                display: false
                            },
                            tooltip: {
                                enabled: false,
                                external: (context) => {
                                    const tooltip = document.getElementById('chartTooltip');
                                    
                                    // Hide if no tooltip
                                    if (context.tooltip.opacity === 0) {
                                        tooltip.style.opacity = '0';
                                        return;
                                    }
                                    
                                    // Set tooltip content
                                    const value = context.tooltip.dataPoints[0].raw;
                                    const index = context.tooltip.dataPoints[0].dataIndex;
                                    const timeAgo = this.maxHistory - index - 1;
                                    
                                    document.getElementById('tooltipValue').textContent = value.toFixed(1) + '°C';
                                    document.getElementById('tooltipTime').textContent = 
                                        timeAgo === 0 ? 'Just now' : `${timeAgo} second${timeAgo !== 1 ? 's' : ''} ago`;
                                    
                                    // Position tooltip
                                    const chartRect = context.chart.canvas.getBoundingClientRect();
                                    const left = chartRect.left + context.tooltip.caretX;
                                    const top = chartRect.top + context.tooltip.caretY;
                                    
                                    tooltip.style.left = left + 'px';
                                    tooltip.style.top = (top - 50) + 'px';
                                    tooltip.style.opacity = '1';
                                }
                            }
                        },
                        interaction: {
                            intersect: false,
                            mode: 'index'
                        }
                    }
                });
                
                // Resize handler
                window.addEventListener('resize', () => {
                    if (this.chart) {
                        this.chart.resize();
                    }
                });
            }

            updateChart() {
                if (!this.chart || this.tempHistory.length === 0) return;
                
                // Update chart data
                this.chart.data.datasets[0].data = this.tempHistory;
                
                // Adjust y-axis scale if needed
                const currentMin = Math.min(...this.tempHistory);
                const currentMax = Math.max(...this.tempHistory);
                
                if (currentMin < this.minTemp || currentMax > this.maxTemp) {
                    this.minTemp = Math.max(0, Math.floor(currentMin / 10) * 10);
                    this.maxTemp = Math.min(100, Math.ceil(currentMax / 10) * 10);
                    this.chart.options.scales.y.min = this.minTemp;
                    this.chart.options.scales.y.max = this.maxTemp;
                }
                
                this.chart.update();
            }

            updateDisplay(temp, stats, allTemps, fanSpeeds) {
                // Update main temperature display
                const tempValue = document.getElementById('tempValue');
                const statusBadge = document.getElementById('statusBadge');
                const statusText = document.getElementById('statusText');
                
                tempValue.textContent = Math.round(temp);

                // Update temperature class
                tempValue.className = 'temp-value';
                if (temp > 70) {
                    tempValue.classList.add('temp-hot');
                } else if (temp > 55) {
                    tempValue.classList.add('temp-warm');
                } else {
                    tempValue.classList.add('temp-normal');
                }

                // Update status badge
                statusBadge.className = 'status-badge';
                if (temp > 75) {
                    statusBadge.classList.add('status-hot');
                    statusText.textContent = 'High Temperature';
                } else if (temp > 60) {
                    statusBadge.classList.add('status-warm');
                    statusText.textContent = 'Elevated Temperature';
                } else {
                    statusBadge.classList.add('status-normal');
                    statusText.textContent = 'Normal Operation';
                }

                // Update stats
                if (stats) {
                    document.getElementById('avgTemp').textContent = Math.round(stats.avg_temp) + '°C';
                    document.getElementById('maxTemp').textContent = Math.round(stats.max_temp) + '°C';
                    document.getElementById('minTemp').textContent = Math.round(stats.min_temp) + '°C';
                }

                // Update thermal zones
                if (allTemps) {
                    const zonesList = document.getElementById('zonesList');
                    const zoneCount = document.getElementById('zoneCount');
                    
                    zonesList.innerHTML = '';
                    zoneCount.textContent = Object.keys(allTemps).length;
                    
                    Object.values(allTemps).forEach(zone => {
                        const zoneItem = document.createElement('div');
                        zoneItem.className = 'zone-item';
                        zoneItem.innerHTML = `
                            <div class="zone-name">${zone.type || 'Unknown'}</div>
                            <div class="zone-temp">${Math.round(zone.temperature)}°C</div>
                        `;
                        zonesList.appendChild(zoneItem);
                    });
                }

                // Update fan speeds
                if (fanSpeeds) {
                    const fansList = document.getElementById('fansList');
                    fansList.innerHTML = '';
                    
                    if (Object.keys(fanSpeeds).length === 0) {
                        fansList.innerHTML = '<div class="zone-item"><div class="zone-name">No fans detected</div></div>';
                    } else {
                        Object.values(fanSpeeds).forEach(fan => {
                            const fanItem = document.createElement('div');
                            fanItem.className = 'zone-item';
                            fanItem.innerHTML = `
                                <div class="zone-name">${fan.label || fan.device}</div>
                                <div class="zone-temp">${fan.speed} RPM</div>
                            `;
                            fansList.appendChild(fanItem);
                        });
                    }
                }
            }

            async startMonitoring() {
                let updateInProgress = false;
                
                const update = async () => {
                    if (updateInProgress) {
                        setTimeout(update, 1000);
                        return;
                    }
                    
                    updateInProgress = true;
                    
                    try {
                        const [temp, stats, allTemps, fanSpeeds] = await Promise.all([
                            this.readTemperature(),
                            this.readStats(),
                            this.readAllTemperatures(),
                            this.readFanSpeeds()
                        ]);
                        
                        if (temp !== null) {
                            this.tempHistory.push(temp);
                            if (this.tempHistory.length > this.maxHistory) {
                                this.tempHistory.shift();
                            }
                            
                            this.updateDisplay(temp, stats, allTemps, fanSpeeds);
                            this.updateChart();
                        }
                        
                    } catch (error) {
                        console.error('Error in monitoring loop:', error);
                        this.showError('Monitoring error: ' + error.message);
                    } finally {
                        updateInProgress = false;
                    }
                    
                    setTimeout(update, 1000);
                };
                
                update();
            }
        }

        // Initialize the monitor when page loads
        document.addEventListener('DOMContentLoaded', () => {
            new CPUTempMonitor();
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("Enhanced CPU Temperature Monitor Backend")
    print("=" * 40)
    print(f"Thermal zones discovered: {len(thermal_monitor.thermal_zones)}")
    print(f"Fan sensors discovered: {len(thermal_monitor.fan_sensors)}")
    print("\nStarting Flask server...")
    print("Access the monitor at: http://localhost:5000")
    print("API endpoints:")
    print("  - /api/temperature - Current CPU temperature")
    print("  - /api/stats - Temperature statistics")
    print("  - /api/all-temperatures - All thermal zones")
    print("  - /api/zones - Thermal zone information")
    print("  - /api/fans - Current fan speeds")
    print("  - /api/fan-sensors - Fan sensor information")
    print("\nPress Ctrl+C to stop")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
