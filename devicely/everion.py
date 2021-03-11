"""
Module to process Everion data
"""
import os
import glob
import random
import numpy as np
import pandas as pd

class EverionReader:

    SIGNAL_TAGS = {
        6: 'heart_rate',
        7: 'oxygen_saturation',
        8: 'perfusion_index',
        9: 'motion_activity',
        10: 'activity_classification',
        11: 'heart_rate_variability',
        12: 'respiration_rate',
        13: 'energy',
        15: 'ctemp',
        19: 'temperature_local',
        20: 'barometer_pressure',
        21: 'gsr_electrode',
        22: 'health_score',
        23: 'relax_stress_intensity_score',
        24: 'sleep_quality_index_score',
        25: 'training_effect_score',
        26: 'activity_score',
        66: 'richness_score',
        68: 'heart_rate_quality',
        69: 'oxygen_saturation_quality',
        70: 'blood_pulse_wave',
        71: 'number_of_steps',
        72: 'activity_classification_quality',
        73: 'energy_quality',
        74: 'heart_rate_variability_quality',
        75: 'respiration_rate_quality',
        76: 'ctemp_quality',
        118: 'temperature_object',
        119: 'temperature_barometer',
        133: 'perfusion_index_quality',
        134: 'blood_pulse_wave_quality'
    }

    SENSOR_TAGS = {
        80: 'led1_data',
        81: 'led2_data',
        82: 'led3_data',
        83: 'led4_data',
        84: 'accx_data',
        85: 'accy_data',
        86: 'accz_data',
        88: 'led2_current',
        89: 'led3_current',
        90: 'led4_current',
        91: 'current_offset',
        92: 'compressed_data'
    }

    FEATURE_TAGS = {
        14: 'inter_pulse_interval',
        17: 'pis',
        18: 'pid',
        77: 'inter_pulse_deviation',
        78: 'pis_quality',
        79: 'pid_quality'
    }

    default_signal_tags = [6, 7, 11, 12, 15, 19, 20, 21, 118, 119]
    default_sensor_tags = [80, 81, 82, 83, 84, 85, 86]
    default_feature_tags = [14]

    ACC_NAMES = ['accx_data', 'accy_data', 'accz_data']

    def __init__(self, path, signal_tags=default_signal_tags, sensor_tags=default_sensor_tags, feature_tags=default_feature_tags):
        if not os.path.isdir(path):
            raise OSError(f"path parameter needs to point to a directory")

        for tag in signal_tags:
            if tag not in self.SIGNAL_TAGS:
                raise KeyError(
                    f"Tag with number {tag} is not a valid signal tag. See EverionReader.SIGNAL_TAGS for a list of valid signal tags.")
        for tag in feature_tags:
            if tag not in self.FEATURE_TAGS:
                raise KeyError(
                    f"Tag with number {tag} is not a valid feature tag. See EverionReader.FEATURE_TAGS for a list of valid feature tags.")
        for tag in sensor_tags:
            if tag not in self.SENSOR_TAGS:
                raise KeyError(
                    f"Tag with number {tag} is not a valid sensor tag. See EverionReader.SENSOR_TAGS for a list of valid sensor tags.")

        self.selected_signal_tags = signal_tags
        self.selected_feature_tags = feature_tags
        self.selected_sensor_tags = sensor_tags

        self._init_filelist(path)

        self.aggregates = self._read_file('aggregates')
        self.analytics_events = self._read_file('analytics_events')
        self.attributes_dailys = self._read_file('attributes_dailys')
        self.everion_events = self._read_file('everion_events')
        self.features = self._read_file('features')
        self.sensors = self._read_file('sensor_data')
        self.signals = self._read_file('signals')

        self._join()

    def _init_filelist(self, path):
        file_patterns = ['aggregates', 'analytics_events', 'attributes_dailys',
                         'everion_events', 'features', 'sensor_data', 'signals']
        self.filelist = dict()
        for pattern in file_patterns:
            filenames = glob.glob(os.path.join(path, f"*{pattern}*"))
            if len(filenames) == 0:
                print(
                    f"No file found in path {path} that matches the pattern *{pattern}*. Continuing with the remaining files.")
                continue
            if len(filenames) > 1:
                print(
                    f"Multiple files found in {path} that match the pattern *{pattern}*. Continuing with the remaining files because this is ambiguous.")
                continue
            self.filelist[pattern] = filenames.pop()

    def _read_file(self, filepattern):
        try:
            filepath = self.filelist[filepattern]
        except KeyError:
            return None

        dateparse = {"parse_dates": ['time'],
                    "date_parser": lambda x: pd.to_datetime(x, unit='s')}
        df = pd.read_csv(filepath, **dateparse).drop_duplicates()

        try:
            df['values'] = df['values'].astype(float)
        except ValueError:
            df[['values', 'quality']] = df['values'].str.split(
                ';', expand=True).astype(float)
        return df

    def _join(self):
        signals = self._convert_single_dataframe(
            self.signals, self.selected_signal_tags)
        features = self._convert_single_dataframe(
            self.features, self.selected_feature_tags)
        sensors = self._convert_single_dataframe(
            self.sensors, self.selected_sensor_tags)
        dataframes = [signals, features, sensors]
        self.data = pd.DataFrame()
        for df in dataframes:
            self.data = self.data.join(df, how='outer')

        if all(x in set(self.data.columns) for x in self.ACC_NAMES):
            self.data['acc_mag'] = np.linalg.norm(self.data[self.ACC_NAMES], axis='1')

    def _convert_single_dataframe(self, df, selected_tags=None):
        if df is None:
            return pd.DataFrame()
        df = df.drop_duplicates()
        if selected_tags is not None:
            df = df[df['tag'].isin(selected_tags)]

        df['time'] = df['time'].astype(int) / 10**9
        timestamps_min_and_count = df.groupby('time').agg(
            count_min=pd.NamedAgg(column='count', aggfunc='min'),
            count_range=pd.NamedAgg(
                column='count', aggfunc=lambda s: s.max() - s.min() + 1)
        ).reset_index()
        df = df.merge(timestamps_min_and_count, on='time')
        df['time'] += (df['count'] - df['count_min']) / df['count_range']
        df['time'] = pd.to_datetime(df['time'], unit='s')

        new_df = pd.DataFrame()
        for tag, group_df in df.groupby('tag'):
            tag_name = self._tag_name(tag)
            quality_name = f"{tag_name}_deviation" if tag == 14 else f"{tag_name}_quality"
            sub_df = group_df.rename(columns={'values': tag_name, 'quality': quality_name})
            sub_df.drop(columns=['count', 'streamType', 'tag', 'count_min', 'count_range'], inplace=True)
            sub_df.dropna(axis=1, inplace=True)
            if sub_df.empty or (sub_df[tag_name] == 0).all():
                continue
            sub_df = sub_df.set_index('time', verify_integrity=True)
            sub_df = sub_df.sort_index()
            new_df = new_df.join(sub_df, how='outer')

        return new_df

    def _tag_name(self, tag_number):
        try:
            return self.SIGNAL_TAGS[tag_number]
        except KeyError:
            pass
        try:
            return self.SENSOR_TAGS[tag_number]
        except KeyError:
            pass
        try:
            return self.FEATURE_TAGS[tag_number]
        except KeyError:
            pass
        raise KeyError(
            f"no corresponding tag name for tag number {tag_number}")

    def write(self, path):
        if not os.path.exists(path):
            os.mkdir(path)
        if self.aggregates is not None:
            self._write_single_df(self.aggregates, os.path.join(path, 'aggregates.csv'))
        if self.analytics_events is not None:
            self._write_single_df(self.analytics_events, os.path.join(path, "analytics_events.csv"))
        if self.attributes_dailys is not None:
            self._write_single_df(self.attributes_dailys, os.path.join(path, "attributes_dailys.csv"))
        if self.everion_events is not None:
            self._write_single_df(self.everion_events, os.path.join(path, "everion_events.csv"))
        if self.features is not None:
            self._write_single_df(self.features, os.path.join(path, "features.csv"))
        if self.sensors is not None:
            self._write_single_df(self.sensors, os.path.join(path, "sensor_data.csv"))
        if self.signals is not None:
            self._write_single_df(self.signals, os.path.join(path, "signals.csv"))

    def _write_single_df(self, df, filepath):
        writing_df = df.copy()
        writing_df['time'] = (writing_df['time'].astype(int) / 10**9).astype(int)
        if 'quality' in writing_df.columns:
            writing_df['values'] = writing_df['values'].astype(str)
            quality_col = writing_df['quality'].dropna().astype(str)
            writing_df.loc[quality_col.index, 'values'] += ';' + quality_col
            writing_df.drop(columns=['quality'], inplace=True)

        writing_df.to_csv(filepath, index=None)

    def timeshift(self, shift='random'):
        if shift == 'random':
            one_month = pd.Timedelta('30 days').value
            two_years = pd.Timedelta('730 days').value
            random_timedelta = - pd.Timedelta(random.uniform(one_month, two_years)).round('s')
            self.timeshift(random_timedelta)
        if isinstance(shift, pd.Timestamp):
            for df in self._raw_dataframes():
                timedeltas = df['time'] - df['time'].min()
                df['time'] = shift + timedeltas
            self._join()
        if isinstance(shift, pd.Timedelta):
            for df in self._raw_dataframes():
                df['time'] += shift
            self._join()

    def _raw_dataframes(self):
        return [df for df in [self.aggregates, self.analytics_events, self.attributes_dailys,
                              self.everion_events, self.features, self.sensors, self.signals]
                if df is not None]
