import React, { useState, useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import MapboxDraw from '@mapbox/mapbox-gl-draw';
import '@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css';
import axios from 'axios';
// Remove MapboxDraw for now until we fix compatibility
import 'maplibre-gl/dist/maplibre-gl.css';
import { Box, AppBar, Toolbar, Typography, Slider, Button, 
         ToggleButton, ToggleButtonGroup, IconButton, Paper } from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { PlayArrow, Pause, FastForward, FastRewind, LocalFireDepartment, Air } from '@mui/icons-material';
import CssBaseline from '@mui/material/CssBaseline';
import * as turf from '@turf/turf';

interface WindVector {
  speed: number;    // m/s
  direction: number; // degrees from north
}

interface SimulationState {
  isRunning: boolean;
  currentTime: Date;
  simulationType: 'physics' | 'ml';
  firePolygon: GeoJSON.Feature | null;
  timelinePosition: number;
  playbackSpeed: number;
  windVector: WindVector;
}

interface FireSpreadData {
  timestamp: string;
  firePerimeter: GeoJSON.Feature;
  smokePlume: GeoJSON.Feature;
}

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
  },
});

// Fire colors for visualization
const FIRE_COLORS = [
  'rgba(255, 0, 0, 0.3)',    // Red core
  'rgba(255, 69, 0, 0.3)',   // Red-orange
  'rgba(255, 140, 0, 0.3)',  // Dark orange
  'rgba(255, 165, 0, 0.3)',  // Orange
  'rgba(255, 215, 0, 0.3)'   // Golden
];

// Smoke colors for visualization
const SMOKE_COLORS = [
  'rgba(128, 128, 128, 0.7)',  // Dark grey
  'rgba(169, 169, 169, 0.6)',  // Grey
  'rgba(192, 192, 192, 0.5)',  // Light grey
  'rgba(211, 211, 211, 0.4)',  // Very light grey
  'rgba(220, 220, 220, 0.3)'   // Almost white
];

const WindControl: React.FC<{
  value: WindVector;
  onChange: (value: WindVector) => void;
  disabled?: boolean;
}> = ({ value, onChange, disabled }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const maxSpeed = 20; // m/s

  const calculateVector = (e: React.MouseEvent | MouseEvent) => {
    if (!containerRef.current) return;
    
    const rect = containerRef.current.getBoundingClientRect();
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    
    // Keep x inverted for correct east/west, invert y for correct north/south
    const x = -(e.clientX - rect.left - centerX);
    const y = (e.clientY - rect.top - centerY);
    
    // Calculate direction (in degrees, 0 is north, clockwise)
    let direction = (Math.atan2(x, y) * 180 / Math.PI + 360) % 360;
    
    // Calculate speed based on distance from center
    const distance = Math.min(Math.sqrt(x * x + y * y), rect.width / 2);
    const speed = (distance / (rect.width / 2)) * maxSpeed;
    
    onChange({ speed, direction });
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (disabled) return;
    isDragging.current = true;
    calculateVector(e);
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging.current || disabled) return;
    calculateVector(e);
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  // Calculate vector endpoint for visualization
  const angle = value.direction * Math.PI / 180;
  const radius = (value.speed / maxSpeed) * 100;
  // Adjust vector calculation to match the direction
  const vectorX = Math.sin(angle) * radius;
  const vectorY = -Math.cos(angle) * radius;

  return (
    <Paper 
      ref={containerRef}
      sx={{
        width: 200,
        height: 200,
        borderRadius: '50%',
        position: 'relative',
        cursor: disabled ? 'default' : 'pointer',
        bgcolor: 'rgba(0, 0, 0, 0.2)',
        border: '2px solid rgba(255, 255, 255, 0.1)',
        overflow: 'visible',
        '&::before': {
          content: '""',
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: '2px',
          height: '2px',
          bgcolor: 'primary.main',
          borderRadius: '50%',
          transform: 'translate(-50%, -50%)',
        }
      }}
      onMouseDown={handleMouseDown}
    >
      {/* Direction markers */}
      <Typography sx={{ position: 'absolute', top: -25, left: '50%', transform: 'translateX(-50%)' }}>N</Typography>
      <Typography sx={{ position: 'absolute', bottom: -25, left: '50%', transform: 'translateX(-50%)' }}>S</Typography>
      <Typography sx={{ position: 'absolute', left: -25, top: '50%', transform: 'translateY(-50%)' }}>W</Typography>
      <Typography sx={{ position: 'absolute', right: -25, top: '50%', transform: 'translateY(-50%)' }}>E</Typography>
      
      {/* Wind vector visualization */}
      <Box sx={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        width: '2px',
        height: `${Math.sqrt(vectorX * vectorX + vectorY * vectorY)}px`,
        bgcolor: 'primary.main',
        transformOrigin: 'top',
        transform: `rotate(${value.direction}deg)`,
        '&::after': {
          content: '""',
          position: 'absolute',
          bottom: -6,
          left: '50%',
          transform: 'translateX(-50%) rotate(45deg)',
          width: 0,
          height: 0,
          borderLeft: '5px solid transparent',
          borderRight: '5px solid transparent',
          borderTop: '8px solid',
          borderTopColor: 'primary.main',
        }
      }} />

      {/* Speed rings */}
      {[0.25, 0.5, 0.75].map((ratio, i) => (
        <Box
          key={i}
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: `${200 * ratio}px`,
            height: `${200 * ratio}px`,
            border: '1px dashed rgba(255, 255, 255, 0.2)',
            borderRadius: '50%',
            transform: 'translate(-50%, -50%)',
          }}
        />
      ))}

      {/* Speed label */}
      <Typography
        sx={{
          position: 'absolute',
          bottom: 10,
          left: '50%',
          transform: 'translateX(-50%)',
          color: 'text.secondary',
        }}
      >
        {value.speed.toFixed(1)} m/s
      </Typography>
    </Paper>
  );
};

const App: React.FC = () => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const draw = useRef<any>(null);
  const animationFrame = useRef<number | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [simulationData, setSimulationData] = useState<FireSpreadData[]>([]);
  const [simState, setSimState] = useState<SimulationState>({
    isRunning: false,
    currentTime: new Date(),
    simulationType: 'physics',
    firePolygon: null,
    timelinePosition: 0,
    playbackSpeed: 1,
    windVector: {
      speed: 0,
      direction: 0
    }
  });

  // Function to create fire marker element
  const createFireMarkerElement = () => {
    const el = document.createElement('div');
    el.className = 'fire-marker';
    el.style.width = '32px';
    el.style.height = '32px';
    
    // Create SVG element for the Material-UI fire icon
    el.innerHTML = `
      <svg viewBox="0 0 24 24" width="32" height="32" fill="#FF4433">
        <path d="M12 12.9l-2.13 2.09c-.56.56-.87 1.29-.87 2.07C9 18.68 10.35 20 12 20s3-1.32 3-2.94c0-.78-.31-1.52-.87-2.07L12 12.9z"/>
        <path d="M16 6l-1 .67c-.36.24-.72.48-1.08.72-.2.14-.41.28-.61.42L12 8.85l-1.31-1.04c-.2-.14-.41-.28-.61-.42L8.96 6.67 8 6c0 1.1.9 2 2 2h4c1.1 0 2-.9 2-2z"/>
        <path d="M12 2s-5 5-5 9c0 2.76 2.24 5 5 5s5-2.24 5-5c0-4-5-9-5-9z"/>
      </svg>
    `;
    return el;
  };

  // Initialize map sources and layers
  const initializeMapLayers = (map: maplibregl.Map) => {
    // Add source for fire perimeter
    map.addSource('fire-perimeter', {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: []
        },
        properties: {}
      }
    });

    // Add source for smoke plume
    map.addSource('smoke-plume', {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: []
        },
        properties: {}
      }
    });

    // Add fire perimeter layer
    map.addLayer({
      id: 'fire-perimeter-layer',
      type: 'fill',
      source: 'fire-perimeter',
      paint: {
        'fill-color': FIRE_COLORS[0],
        'fill-opacity': 0.7
      }
    });

    // Add smoke plume layer
    map.addLayer({
      id: 'smoke-plume-layer',
      type: 'fill',
      source: 'smoke-plume',
      paint: {
        'fill-color': SMOKE_COLORS[0],
        'fill-opacity': 0.5
      }
    });
  };

  // Update visualization based on timeline position
  const updateVisualization = (timelinePos: number) => {
    if (!map.current || simulationData.length === 0) return;

    const dataIndex = Math.floor(timelinePos * (simulationData.length - 1));
    const currentData = simulationData[dataIndex];

    if (currentData) {
      (map.current.getSource('fire-perimeter') as maplibregl.GeoJSONSource)
        .setData(currentData.firePerimeter);
      (map.current.getSource('smoke-plume') as maplibregl.GeoJSONSource)
        .setData(currentData.smokePlume);
    }
  };

  // Animation loop
  const animate = () => {
    if (simState.isRunning && simulationData.length > 0) {
      setSimState(prev => {
        const newPos = prev.timelinePosition + (0.001 * prev.playbackSpeed);
        return {
          ...prev,
          timelinePosition: newPos >= 1 ? 0 : newPos
        };
      });
      animationFrame.current = requestAnimationFrame(animate);
    }
  };

  // Effect for handling animation
  useEffect(() => {
    if (simState.isRunning) {
      animationFrame.current = requestAnimationFrame(animate);
    }
    return () => {
      if (animationFrame.current) {
        cancelAnimationFrame(animationFrame.current);
      }
    };
  }, [simState.isRunning]);

  // Effect for updating visualization
  useEffect(() => {
    updateVisualization(simState.timelinePosition);
  }, [simState.timelinePosition, simulationData]);

  useEffect(() => {
    if (!map.current && mapContainer.current) {
      try {
        console.log('Initializing map...');
        map.current = new maplibregl.Map({
          container: mapContainer.current,
          style: {
            version: 8,
            sources: {
              'osm': {
                type: 'raster',
                tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                tileSize: 256,
                attribution: '© OpenStreetMap contributors'
              }
            },
            layers: [{
              id: 'osm',
              type: 'raster',
              source: 'osm',
              minzoom: 0,
              maxzoom: 19
            }]
          },
          center: [-118.2437, 34.0522], // Los Angeles
          zoom: 9
        });

        // Wait for both style and source to load before adding layers
        map.current.on('style.load', () => {
          console.log('Map style loaded successfully');
          
          // Initialize map layers
          initializeMapLayers(map.current!);

          // Initialize Mapbox Draw
          draw.current = new MapboxDraw({
            displayControlsDefault: false,
            controls: {
              polygon: true,
              trash: true
            },
            defaultMode: 'draw_polygon',
            styles: [
              // Styling for the drawn polygon
              {
                id: 'gl-draw-polygon-fill',
                type: 'fill',
                filter: ['all', ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']],
                paint: {
                  'fill-color': '#ff4433',
                  'fill-outline-color': '#ff4433',
                  'fill-opacity': 0.3
                }
              },
              // Styling for the polygon outline
              {
                id: 'gl-draw-polygon-stroke',
                type: 'line',
                filter: ['all', ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']],
                layout: {
                  'line-cap': 'round',
                  'line-join': 'round'
                },
                paint: {
                  'line-color': '#ff4433',
                  'line-width': 2,
                  'line-dasharray': ["literal", [2, 2]]
                }
              },
              // Styling for vertices
              {
                id: 'gl-draw-polygon-and-line-vertex-active',
                type: 'circle',
                filter: ['all', ['==', 'meta', 'vertex'], ['==', '$type', 'Point']],
                paint: {
                  'circle-radius': 6,
                  'circle-color': '#fff',
                  'circle-stroke-color': '#ff4433',
                  'circle-stroke-width': 2
                }
              }
            ]
          });

          // Add draw controls to the map
          map.current!.addControl(draw.current);

          // Add draw event listeners
          map.current!.on('draw.create', (e) => {
            const polygon = e.features[0];
            setSimState(prev => ({
              ...prev,
              firePolygon: polygon
            }));
            console.log('Fire polygon drawn:', polygon);
          });

          map.current!.on('draw.delete', () => {
            setSimState(prev => ({
              ...prev,
              firePolygon: null
            }));
            console.log('Fire polygon deleted');
          });

          map.current!.on('draw.update', (e) => {
            const polygon = e.features[0];
            setSimState(prev => ({
              ...prev,
              firePolygon: polygon
            }));
            console.log('Fire polygon updated:', polygon);
          });

          // Add navigation controls
          map.current!.addControl(new maplibregl.NavigationControl());
        });

        map.current.on('error', (e) => {
          console.error('Map error:', e);
          setMapError(e.error?.message || 'An error occurred loading the map');
        });

      } catch (error) {
        console.error('Error initializing map:', error);
        setMapError(error instanceof Error ? error.message : 'Failed to initialize map');
      }
    }

    // Cleanup function
    return () => {
      if (map.current) {
        if (draw.current) {
          map.current.removeControl(draw.current);
        }
        console.log('Cleaning up map...');
        map.current.remove();
        map.current = null;
      }
    };
  }, []);

  const toggleSimulation = async () => {
    if (!simState.firePolygon) {
      setMapError('Please draw a fire polygon on the map first');
      return;
    }

    if (!simState.isRunning) {
      try {
        // Calculate the centroid of the polygon
        const centroid = turf.centroid(simState.firePolygon);
        const coordinates = (simState.firePolygon.geometry as GeoJSON.Polygon).coordinates[0];
        const startPoint = (centroid.geometry as GeoJSON.Point).coordinates as [number, number];

        const response = await axios.post('http://localhost:8000/api/simulate', {
          start_point: startPoint,
          start_time: simState.currentTime.toISOString(),
          duration_hours: 24,
          time_step_minutes: 30,
          initial_polygon: coordinates,
          initial_wind: {
            speed: simState.windVector.speed,
            direction: simState.windVector.direction
          }
        });

        setSimulationData(response.data.simulation_data);
        setMapError(null);
      } catch (error) {
        console.error('Simulation error:', error);
        setMapError('Failed to start simulation');
        return;
      }
    }

    setSimState(prev => ({ ...prev, isRunning: !prev.isRunning }));
  };

  const handleTimelineChange = (event: Event, value: number | number[]) => {
    setSimState(prev => ({
      ...prev,
      timelinePosition: value as number
    }));
  };

  const handlePlaybackSpeedChange = (speed: number) => {
    setSimState(prev => ({ ...prev, playbackSpeed: speed }));
  };

  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <Box sx={{ 
        height: '100vh', 
        display: 'flex', 
        flexDirection: 'column',
        bgcolor: 'background.default',
        color: 'text.primary'
      }}>
        <AppBar position="static">
          <Toolbar>
            <Typography variant="h6">
              Predict What We Breathe - Fire Simulation Digital Twin
            </Typography>
          </Toolbar>
        </AppBar>

        <Box sx={{ flexGrow: 1, position: 'relative' }}>
          <div ref={mapContainer} style={{ 
            height: '100%',
            width: '100%',
            position: 'absolute'
          }} />
          
          {/* Wind Control Overlay */}
          <Box sx={{ 
            position: 'absolute', 
            top: 40, 
            right: 40,
            bgcolor: 'rgba(0,0,0,0.85)',
            p: 4,
            borderRadius: 2,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 2,
            zIndex: 1,
            boxShadow: '0 4px 6px rgba(0,0,0,0.1)'
          }}>
            <Typography variant="subtitle1" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Air /> Wind Control
            </Typography>
            <WindControl
              value={simState.windVector}
              onChange={(windVector) => setSimState(prev => ({ ...prev, windVector }))}
              disabled={simState.isRunning}
            />
          </Box>
          
          {mapError && (
            <Box sx={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              bgcolor: 'error.main',
              color: 'error.contrastText',
              p: 2,
              borderRadius: 1
            }}>
              <Typography>{mapError}</Typography>
            </Box>
          )}
          
          <Box sx={{ 
            position: 'absolute', 
            bottom: 20, 
            left: 20, 
            right: 20, 
            bgcolor: 'rgba(0,0,0,0.8)',
            p: 2,
            borderRadius: 1,
            display: 'flex',
            gap: 2,
            alignItems: 'flex-start'
          }}>
            <Box sx={{ flex: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <Typography sx={{ mr: 2 }}>Simulation Controls</Typography>
                <IconButton 
                  onClick={() => handlePlaybackSpeedChange(simState.playbackSpeed / 2)}
                  disabled={!simulationData.length}
                >
                  <FastRewind />
                </IconButton>
                <IconButton 
                  onClick={toggleSimulation}
                  color={simState.isRunning ? "error" : "primary"}
                >
                  {simState.isRunning ? <Pause /> : <PlayArrow />}
                </IconButton>
                <IconButton 
                  onClick={() => handlePlaybackSpeedChange(simState.playbackSpeed * 2)}
                  disabled={!simulationData.length}
                >
                  <FastForward />
                </IconButton>
                <Typography sx={{ ml: 2 }}>
                  Speed: {simState.playbackSpeed}x
                </Typography>
              </Box>

              <Typography>Timeline</Typography>
              <Slider
                min={0}
                max={1}
                step={0.001}
                value={simState.timelinePosition}
                onChange={handleTimelineChange}
                disabled={!simulationData.length}
                sx={{ mt: 1 }}
              />

              <Box sx={{ mt: 2, display: 'flex', alignItems: 'center' }}>
                <ToggleButtonGroup
                  value={simState.simulationType}
                  exclusive
                  onChange={(e, value) => setSimState(prev => ({ ...prev, simulationType: value }))}
                  size="small"
                >
                  <ToggleButton value="physics">Physics Engine</ToggleButton>
                  <ToggleButton value="ml" disabled>ML Model (Coming Soon)</ToggleButton>
                </ToggleButtonGroup>
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    </ThemeProvider>
  );
};

export default App;
