import os
import subprocess
import shutil
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
import pickle
from datetime import datetime, timedelta
import cv2

class HYSPLITData:
    '''
    Gets the HYSPLIT data.
    Pipeline:
        - Run HYSPLIT concentration model using configuration files
        - Parse cdump files into dataframes
        - Interpolate data onto standardized grids
        - Create samples from a sliding window of frames
            - (samples, frames, row, col, channel)

    Members:
        data: The complete processed HYSPLIT data
        sequence_info: Metadata about the sequence (day, hour)
        grid_info: Information about the grid used
    '''
    def __init__(
        self,
        start_location,
        start_date,
        end_date,
        extent,
        base_dir,
        working_dir,
        exec_dir,
        bdy_files_dir,
        output_dir,
        met_file,
        frames_per_sample=1,
        dim=200,
        verbose=False
    ):
        self.start_location = start_location
        self.base_dir = base_dir
        self.working_dir = working_dir
        self.exec_dir = exec_dir
        self.bdy_files_dir = bdy_files_dir
        self.output_dir = output_dir
        self.met_file = met_file
        self.extent = extent
        self.dim = dim
        self.verbose = verbose
        
        # Convert date strings to datetime objects for processing
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d-%H")
        self.end_date = datetime.strptime(end_date, "%Y-%m-%d-%H")
        
        # Run pipeline
        self.__run_hysplit_simulations()
        cdump_files = self.__collect_cdump_files()
        subregion_frames = self.__process_cdump_files(cdump_files)
        preprocessed_frames = self.__interpolate_and_add_channel_axis(subregion_frames, dim)
        processed_ds = self.__sliding_window_of(preprocessed_frames, frames_per_sample)
        
        # Attributes
        self.data = processed_ds
        
    def __run_hysplit_simulations(self):
        """Run a single HYSPLIT simulation covering the entire date range"""
        if self.verbose:
            print("Running HYSPLIT simulation...")
            
        # Get start date components
        # year = self.start_date.year % 100  # Last two digits of year
        # month = self.start_date.month
        # day = self.start_date.day
        # hour = self.start_date.hour

        # fake date because we don't have live data yet
        year = 25
        month = 1
        day = 10
        hour = 0
        
        # Create HYSPLIT configuration files
        self.__create_ascdata_cfg()
        self.__create_control_file(year, month, day, hour, self.start_location[0], self.start_location[1])
        
        # Run HYSPLIT once for the entire period
        self.__run_hysplit_conc()
        

    def __create_control_file(self, year, month, day, hour, lat, lon, height=500):
        """Create a HYSPLIT CONTROL file for PM2.5 concentration simulation"""
        control_path = os.path.join(self.working_dir, "CONTROL")
        
        # Make sure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        with open(control_path, 'w') as f:
            f.write(f"{year:02d} {month:02d} {day:02d} {hour:02d}\n")          # Start year, month, day, hour
            f.write("1\n")                       # Number of starting locations
            f.write(f"{lat} {lon} {height}\n")       # Lat, lon, height (m)
            f.write("72\n")                      # Run duration (hours)
            f.write("0\n")                       # Vertical motion option
            f.write("10000.0\n")                 # Mass release amount
            f.write("1\n")                       # Number of met files
            f.write(f"{self.working_dir}/\n")             # Met file directory
            f.write(f"{self.met_file}\n")             # Met file name
            f.write("1\n")                       # Pollutant type count
            f.write("PM25\n")                    # Pollutant name
            f.write("1.0\n")                     # Emission rate (per hour)
            f.write("1.0\n")                    # Averaging time (hours)
            f.write("00 00 00 00 00\n")          # Release start (yy mm dd hh mm)
            f.write("1\n")                       # Number of grid levels
            f.write("0.0 0.0\n")                 # Grid center (lat, lon)
            f.write("0.5 0.5\n")               # Grid spacing (lat, lon)
            f.write("200.0 200.0\n")               # Grid span (lat, lon)
            f.write("./\n")                      # Output directory
            f.write("cdump\n")                   # Output file name
            f.write("1\n")                       # Number of vertical levels
            f.write("100\n")                     # Height of level (m)
            f.write("00 00 00 00 00\n")          # Sampling start (yy mm dd hh mm)
            f.write("00 03 00 00 00\n")          # Sampling stop (yy mm dd hh mm)
            f.write("00 01 00\n")                # Sampling interval (hh mm ss)
            f.write("1\n")                       # Number of parameters in addition
            f.write("0.0 0.0 0.0\n")             # Particle parameters
            f.write("0.0 0.0 0.0 0.0 0.0\n")     # Deposition parameters
            f.write("0.0 0.0 0.0\n")             # Additional deposition parameters
            f.write("0.0\n")                     # Radioactive decay half-life (days)
            f.write("0.0\n")                     # Pollutant resuspension factor (1/m)
        
        if self.verbose:
            print(f"Created CONTROL file for date: {year:02d}-{month:02d}-{day:02d} {hour:02d}:00")
        
        return control_path

    def __create_ascdata_cfg(self):
        """Create ASCDATA.CFG file for land use data"""
        ascdata_path = os.path.join(self.working_dir, "ASCDATA.CFG")
        
        with open(ascdata_path, 'w') as f:
            f.write("-90.0   -180.0  lat/lon of lower left corner\n")
            f.write("1.0     1.0     lat/lon spacing in degrees\n")
            f.write("180     360     lat/lon number of data points\n")
            f.write("2               default land use category\n")
            f.write("0.2             default roughness length (m)\n")
            f.write(f"{self.bdy_files_dir}/  directory of files\n")
        
        return ascdata_path
    
    def __run_hysplit_conc(self):
        """Run the HYSPLIT concentration model"""
        # Change to working directory
        original_dir = os.getcwd()
        os.chdir(self.working_dir)
        
        # Path to hycs_std executable
        hycs_std_path = os.path.join(self.exec_dir, "hycs_std")
        
        # Run HYSPLIT
        try:
            subprocess.run([hycs_std_path], check=True)
            if self.verbose:
                print("HYSPLIT concentration run completed successfully")
            
            # Find and copy output files to output directory
            cdump_files = glob.glob("cdump_*_*")
            for cdump_file in cdump_files:
                if os.path.exists(cdump_file):
                    output_path = os.path.join(self.output_dir, cdump_file)
                    shutil.copy(cdump_file, output_path)
                    
                    # Convert to ASCII with simpler naming
                    con2asc_path = os.path.join(self.exec_dir, "con2asc")
                    if os.path.exists(con2asc_path):
                        # Use a simpler output filename that doesn't add timestamps
                        ascii_output = os.path.join(self.output_dir, cdump_file + "_asc")
                        subprocess.run([
                            con2asc_path, 
                            "-i"+cdump_file, 
                            "-o"+ascii_output
                        ], check=True)
            
            # Return to original directory
            os.chdir(original_dir)
            return True
        except subprocess.CalledProcessError as e:
            if self.verbose:
                print(f"Error running HYSPLIT: {e}")
            # Return to original directory
            os.chdir(original_dir)
            return False
    
    def __collect_cdump_files(self):
        """Find all cdump files in the output directory"""
        # Find all cdump files
        cdump_files = sorted(glob.glob(os.path.join(self.output_dir, "cdump_*_*")))
        if not cdump_files:
            # Try ASCII versions
            cdump_files = sorted(glob.glob(os.path.join(self.output_dir, "cdump_*_*_asc")))
        
        if not cdump_files:
            # Try the working directory if output_dir doesn't work
            cdump_files = sorted(glob.glob(os.path.join(self.working_dir, "cdump_*_*")))

        if not cdump_files and self.verbose:
            print("No cdump files found. Please check the file paths.")
        else:
            if self.verbose:
                print(f"Found {len(cdump_files)} cdump files")
                
        return cdump_files
    
    def __process_cdump_files(self, cdump_files):
        """Process cdump files into dataframes and then into frames"""
        # Extract bounding box coordinates
        lon_min, lon_max, lat_min, lat_max = self.extent
        
        # Process each cdump file
        sequence_data = []
        sequence_info = []  # To store metadata (day, hour)
        
        for cdump_file in cdump_files:
            # Extract time information from filename
            filename = os.path.basename(cdump_file)
            day_hour = filename.replace('cdump_', '').split('_')
            day = int(day_hour[0])
            hour = int(day_hour[1])
            
            # Parse the cdump file
            df = self.__parse_cdump(cdump_file)
            
            if len(df) > 3:  # Need at least 3 points for interpolation
                # Extract coordinates and concentration values
                points = df[['LON', 'LAT']].values
                values = df.iloc[:, -1].values  # Assuming the last column is concentration
                
                # Create grid for interpolation
                grid_lon = np.linspace(lon_min, lon_max, self.dim)
                grid_lat = np.linspace(lat_min, lat_max, self.dim)
                grid_lon_mesh, grid_lat_mesh = np.meshgrid(grid_lon, grid_lat)
                
                # Interpolate concentration values onto the standardized grid
                grid_conc = griddata(points, values, (grid_lon_mesh, grid_lat_mesh), 
                                   method='linear', fill_value=0)
                
                # Save the grid for processing
                sequence_data.append(grid_conc)
                sequence_info.append({'day': day, 'hour': hour})
                
                if self.verbose:
                    print(f"Processed Day {day}, Hour {hour}")
            else:
                if self.verbose:
                    print(f"Not enough data points in {filename} for interpolation")
        
        # Save metadata
        self.sequence_info = sequence_info
        self.grid_info = {
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lon_min': lon_min,
            'lon_max': lon_max,
            'resolution': self.dim
        }
        
        # Convert to numpy array
        return np.array(sequence_data)
    
    def __parse_cdump(self, file_path):
        """Parse HYSPLIT cdump file into a pandas DataFrame"""
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            # Find the data section (after the header)
            for i, line in enumerate(lines):
                if 'DAY HR' in line:
                    header_line = i
                    break
            
            # Column names from the header line
            columns = lines[header_line].strip().split()
            
            # Parse data lines
            data = []
            for line in lines[header_line+1:]:
                if line.strip():  # Skip empty lines
                    values = line.strip().split()
                    if len(values) == len(columns):
                        data.append(values)
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=columns)
            
            # Convert data types
            for col in df.columns:
                if col in ['DAY', 'HR']:
                    df[col] = df[col].astype(int)
                elif col in ['LAT', 'LON']:
                    df[col] = df[col].astype(float)
                else:  # PM2500100 or other concentration columns
                    # Handle scientific notation with 'E' format
                    df[col] = df[col].apply(lambda x: float(x.replace('E', 'e')))
            
            return df
        except Exception as e:
            if self.verbose:
                print(f"Error parsing cdump file {file_path}: {e}")
            # Return empty DataFrame with expected columns
            return pd.DataFrame(columns=['DAY', 'HR', 'LAT', 'LON', 'PM25'])
    
    def __interpolate_and_add_channel_axis(self, subregion_ds, dim):
        """Interpolate frames to target dimensions and add channel axis"""
        n_frames = len(subregion_ds)
        channels = 1
        frames = np.empty(shape=(n_frames, dim, dim, channels))

        # Interpolate and add channel axis
        for i, frame in enumerate(subregion_ds):
            if frame.shape[0] != dim or frame.shape[1] != dim:
                new_frame = cv2.resize(frame, (dim, dim))
            else:
                new_frame = frame
            new_frame = np.reshape(new_frame, (dim, dim, channels))
            frames[i] = new_frame

        return frames
    
    def __sliding_window_of(self, frames, window_size, step_size=1):
        """
        Creates samples from frames using a sliding window approach.
        
        Arguments:
            frames: A numpy array of the shape (num_frames, row, col, channels)
            window_size: The desired number of frames per sample
            step_size: The size of each step for the sliding window
            
        Returns:
            A numpy array of the shape (num_samples, num_frames, row, col, channels)
        """
        n_frames, row, col, channels = frames.shape
        
        # Calculate number of samples based on window size and step size
        n_samples = max(0, (n_frames - window_size) // step_size + 1)
        
        # If no samples can be created, return empty array with correct shape
        if n_samples == 0:
            return np.empty((0, window_size, row, col, channels))
        
        samples = np.empty((n_samples, window_size, row, col, channels))
        
        for i in range(n_samples):
            start_idx = i * step_size
            end_idx = start_idx + window_size
            samples[i] = frames[start_idx:end_idx]
        
        return samples
