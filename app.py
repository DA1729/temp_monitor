#!/usr/bin/env python3
"""
CPU Temperature Monitor Flask Backend
Reads from Linux thermal zones and serves temperature data via REST API
"""

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
        self.temperature_history = deque(maxlen=100)
        self.current_temps = {}
        self.stats = {
            'avg_temp': 0,
            'max_temp': 0,
            'min_temp': 100,
            'cpu_temp': 0
        }
        self.discover_thermal_zones()
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
    
    def start_monitoring(self):
        """Start background temperature monitoring"""
        def monitor_loop():
            while True:
                self.update_temperatures()
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

# HTML Template (you can also serve this as a separate file)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CPU Temperature Monitor</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
            color: #ffffff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .container {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 24px;
            padding: 40px;
            width: 480px;
            text-align: center;
            box-shadow: 0 32px 64px rgba(0, 0, 0, 0.3);
            position: relative;
            overflow: hidden;
        }

        .container::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
        }

        .title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #ffffff, #a0a0a0);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .subtitle {
            font-size: 14px;
            color: rgba(255, 255, 255, 0.6);
            margin-bottom: 40px;
            font-weight: 400;
        }

        .temp-display {
            position: relative;
            margin: 40px 0;
        }

        .temp-circle {
            width: 200px;
            height: 200px;
            border-radius: 50%;
            margin: 0 auto 24px;
            position: relative;
            background: conic-gradient(from 0deg, #00ff87, #60efff, #ffffff, #ff6b6b, #ff3838);
            padding: 8px;
            animation: rotate 10s linear infinite;
        }

        .temp-inner {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(15, 15, 35, 0.9);
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            position: relative;
        }

        .temp-value {
            font-size: 48px;
            font-weight: 800;
            line-height: 1;
            background: linear-gradient(135deg, #00ff87, #60efff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .temp-unit {
            font-size: 18px;
            color: rgba(255, 255, 255, 0.7);
            font-weight: 500;
            margin-top: 4px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-top: 32px;
        }

        .stat-card {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 20px;
            transition: all 0.3s ease;
        }

        .stat-card:hover {
            background: rgba(255, 255, 255, 0.08);
            transform: translateY(-2px);
        }

        .stat-label {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.6);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
            font-weight: 600;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: #ffffff;
        }

        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-top: 24px;
            padding: 12px 24px;
            background: rgba(0, 255, 135, 0.1);
            border: 1px solid rgba(0, 255, 135, 0.3);
            border-radius: 32px;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #00ff87;
            animation: pulse 2s infinite;
        }

        .chart-container {
            margin-top: 32px;
            height: 60px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 8px;
            position: relative;
            overflow: hidden;
        }

        .chart-line {
            height: 100%;
            display: flex;
            align-items: end;
            gap: 2px;
        }

        .chart-bar {
            flex: 1;
            background: linear-gradient(to top, #00ff87, #60efff);
            border-radius: 2px;
            transition: height 0.5s ease;
            min-height: 2px;
        }

        .error {
            color: #ff6b6b;
            background: rgba(255, 107, 107, 0.1);
            border: 1px solid rgba(255, 107, 107, 0.3);
            padding: 16px;
            border-radius: 12px;
            margin-top: 20px;
        }

        @keyframes rotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .hot { 
            background: conic-gradient(from 0deg, #ff3838, #ff6b6b, #ffffff, #60efff, #00ff87) !important; 
        }
        .warm { 
            background: conic-gradient(from 0deg, #ff6b6b, #ffaa00, #ffffff, #60efff, #00ff87) !important; 
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="title">CPU Temperature</h1>
        <p class="subtitle">Real-time system monitoring</p>
        
        <div class="temp-display">
            <div class="temp-circle" id="tempCircle">
                <div class="temp-inner">
                    <div class="temp-value" id="tempValue">--</div>
                    <div class="temp-unit">°C</div>
                </div>
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
        </div>

        <div class="status-indicator" id="statusIndicator">
            <div class="status-dot"></div>
            <span id="statusText">Connecting...</span>
        </div>

        <div class="chart-container">
            <div class="chart-line" id="chartLine">
                <!-- Chart bars will be generated here -->
            </div>
        </div>

        <div id="errorDisplay" class="error" style="display: none;"></div>
    </div>

    <script>
        class CPUTempMonitor {
            constructor() {
                this.tempHistory = [];
                this.maxHistory = 30;
                this.apiBase = '';  // Since we're serving from the same Flask app
                
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

            showError(message) {
                const errorDisplay = document.getElementById('errorDisplay');
                errorDisplay.textContent = message;
                errorDisplay.style.display = 'block';
                setTimeout(() => {
                    errorDisplay.style.display = 'none';
                }, 5000);
            }

            initChart() {
                const chartLine = document.getElementById('chartLine');
                for (let i = 0; i < this.maxHistory; i++) {
                    const bar = document.createElement('div');
                    bar.className = 'chart-bar';
                    bar.style.height = '20%';
                    chartLine.appendChild(bar);
                }
            }

            updateChart(temp) {
                const bars = document.querySelectorAll('.chart-bar');
                const percentage = Math.max(5, Math.min(100, (temp - 20) / 60 * 100));
                
                // Shift existing bars
                for (let i = 0; i < bars.length - 1; i++) {
                    bars[i].style.height = bars[i + 1].style.height;
                }
                
                // Update last bar
                bars[bars.length - 1].style.height = percentage + '%';
            }

            updateDisplay(temp, stats) {
                const tempValue = document.getElementById('tempValue');
                const tempCircle = document.getElementById('tempCircle');
                const statusIndicator = document.getElementById('statusIndicator');
                const statusText = document.getElementById('statusText');
                
                // Update temperature display
                const targetTemp = Math.round(temp);
                tempValue.textContent = targetTemp;

                // Update circle color based on temperature
                tempCircle.className = 'temp-circle';
                if (temp > 70) {
                    tempCircle.classList.add('hot');
                } else if (temp > 55) {
                    tempCircle.classList.add('warm');
                }

                // Update status
                let status, color;
                if (temp > 75) {
                    status = 'High Temperature';
                    color = '#ff3838';
                } else if (temp > 60) {
                    status = 'Elevated Temperature';
                    color = '#ffaa00';
                } else {
                    status = 'Normal Operation';
                    color = '#00ff87';
                }
                
                statusText.textContent = status;
                statusIndicator.style.background = `rgba(${color === '#ff3838' ? '255, 56, 56' : color === '#ffaa00' ? '255, 170, 0' : '0, 255, 135'}, 0.1)`;
                statusIndicator.style.borderColor = `${color}55`;
                statusIndicator.querySelector('.status-dot').style.background = color;

                // Update stats if available
                if (stats) {
                    document.getElementById('avgTemp').textContent = Math.round(stats.avg_temp) + '°C';
                    document.getElementById('maxTemp').textContent = Math.round(stats.max_temp) + '°C';
                }
            }

            async startMonitoring() {
                const update = async () => {
                    try {
                        const temp = await this.readTemperature();
                        const stats = await this.readStats();
                        
                        if (temp !== null) {
                            this.tempHistory.push(temp);
                            if (this.tempHistory.length > this.maxHistory) {
                                this.tempHistory.shift();
                            }
                            
                            this.updateDisplay(temp, stats);
                            this.updateChart(temp);
                        }
                        
                    } catch (error) {
                        console.error('Error in monitoring loop:', error);
                        this.showError('Monitoring error: ' + error.message);
                    }
                    
                    setTimeout(update, 1000);  // Update every second
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
    print("CPU Temperature Monitor Backend")
    print("=" * 40)
    print(f"Thermal zones discovered: {len(thermal_monitor.thermal_zones)}")
    print("\nStarting Flask server...")
    print("Access the monitor at: http://localhost:5000")
    print("API endpoints:")
    print("  - /api/temperature - Current CPU temperature")
    print("  - /api/stats - Temperature statistics")
    print("  - /api/all-temperatures - All thermal zones")
    print("  - /api/zones - Thermal zone information")
    print("\nPress Ctrl+C to stop")
    
    app.run(host='0.0.0.0', port=5000, debug=True)