#!/usr/bin/env python3
from sqlite3 import Connection, Cursor
from types import SimpleNamespace
from numpy import ndarray, array
from typing import List


class Observed(object):
    # The name of the observed table.
    TABLE_NAME = 'OBSERVED_ELL'

    # Our table schema.
    SCHEMA = 'TIME_R TIMESTAMP, POP_NAME TEXT, POP_UID TEXT, SAMPLE_UID TEXT, SAMPLE_SIZE INT, \
              LOCUS TEXT, ELL TEXT, ELL_FREQ FLOAT'

    # Our table fields.
    FIELDS = 'TIME_R, POP_NAME, POP_UID, SAMPLE_UID, SAMPLE_SIZE, LOCUS, ELL, ELL_FREQ'

    @classmethod
    def create_table(cls, cursor: Cursor):
        """ Create the table specified by the schema and name SCHEMA and TABLE_NAME respectively.

        :param cursor: Cursor to the observation database generated by the ALFRED script.
        :return: None.
        """
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE_NAME} (
            {cls.SCHEMA}
        );""")

    @classmethod
    def single_insert(cls, cursor: Cursor, entry: SimpleNamespace):
        """ Given a single entry from an ALFRED TSV file whose entries exist in a SimpleNamespace with the same
        attributes as our FIELDS field, insert this into our TABLE_NAME table.

        :param cursor: Cursor to the observation database generated by the ALFRED script.
        :param entry: SimpleNamespace that holds all fields in FIELDS in lowercase form.
        :return: None.
        """
        cursor.execute(f"""
            INSERT INTO {cls.TABLE_NAME} ({cls.FIELDS})
        );""", list(map(lambda a: getattr(entry, a), cls.FIELDS.lower().split(','))))

    def __init__(self, connection: Connection, uid: List, loci: List, bounds: List[int]):
        """ Constructor. Here we set our database connection object, verify that OBSERVED_ELL has been created, and
        generate several representations of our desired (uid, loci) repeat length frequency.

        :param connection: Connection to the observation database generated by the ALFRED script.
        :param uid: IDs of observed samples to compare to, found in the observed table.
        :param loci: Loci of observed samples (must match with uid), found in the observed table.
        :param bounds: 2 element list of repeat length space inclusive boundaries. [0] = lower, [1] = upper.
        """
        self.connection, self.cursor = connection, connection.cursor()

        # Save the rest of our parameters.
        self.uid, self.loci, self.bounds = uid, loci, bounds

        # Verify that the ALFRED script has been run.
        if not bool(self.cursor.execute(f"""
            SELECT NAME
            FROM sqlite_master
            WHERE type='table' AND NAME='{self.TABLE_NAME}'
        """).fetchone()):
            raise LookupError("'OBSERVED_ELL' not found in observation database. Run the ALFRED script.")

        # Generate the frequency representations of our UID, LOCUS pairs.
        self.tuples_raw = self._generate_tuples_raw()
        self.tuples_array = self._generate_tuples(self.tuples_raw)
        self.dictionary_array = self._generate_dictionaries(self.tuples_raw)
        self.sparse_matrix = self._generate_sparse_matrix(self.tuples_raw, bounds)

    def _generate_tuples_raw(self) -> List:
        """ Query the observation table for (repeat length, frequency) tuples for various UID, LOCUS pairs.

        :return: 2D List of (str, str) tuples representing the (repeat length, frequency) tuples.
        """
        return list(map(lambda a, b: self.cursor.execute("""
            SELECT ELL, ELL_FREQ
            FROM OBSERVED_ELL
            WHERE SAMPLE_UID LIKE ?
            AND LOCUS LIKE ?
        """, (a, b,)).fetchall(), self.uid, self.loci))

    @staticmethod
    def _generate_tuples(tuples_raw: List) -> ndarray:
        """ Generate the (int, float) tuple representation using the raw tuple representation.

        :param tuples_raw: 2D list of (str, str) tuples representing the (repeat length, frequency) tuples.
        :return: 2D list of (int, float) tuples representing the (repeat length, frequency) tuples.
        """
        return array([array([(int(a[0]), float(a[1], )) for a in b]) for b in tuples_raw])

    @staticmethod
    def _generate_dictionaries(tuples_raw: List) -> ndarray:
        """ Generate the dictionary representation (frequencies indexed by repeat lengths) using the raw tuple
        representation.

        :param tuples_raw: 2D list of (str, str) tuples representing the (repeat length, frequency) tuples.
        :return: 1D list of dictionaries representing the (repeat length: frequency) dictionaries.
        """
        return array([{int(a[0]): float(a[1]) for a in b} for b in tuples_raw])

    @staticmethod
    def _generate_sparse_matrix(tuples_raw: List, bounds: List) -> ndarray:
        """ Generate the sparse matrix representation (column = repeat length, row = observation) using the raw tuple
        representation and user-defined boundaries.

        :param tuples_raw: 2D list of (str, str) tuples representing the (repeat length, frequency) tuples.
        :param bounds: Upper and lower bound (in that order) of the repeat unit space.
        :return: 2D list of frequencies (the sparse frequency matrix).
        """
        from numpy import zeros

        # Generate a dictionary representation.
        observation_dictionary = Observed._generate_dictionaries(tuples_raw)

        # Fit our observed distribution into a sparse frequency vector.
        observations = array([zeros(bounds[1] - bounds[0] + 1) for _ in tuples_raw])
        for j, observation in enumerate(observation_dictionary):
            for repeat_unit in observation.keys():
                observations[j, repeat_unit - bounds[0] + 1] = observation[repeat_unit]

        return observations

    def generate_pool(self) -> ndarray:
        """ Using the tuples representation, parse all repeat lengths that exist in this specific observation.

        :return: A 1D array of all repeat lengths associated with this observation.
        """
        return self.tuples_array[:, :, 0].flatten()
