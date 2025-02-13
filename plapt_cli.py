import argparse
import sys
from typing import List, Tuple, Union, Dict
from plapt import Plapt
import json 
import csv
import warnings
from pathlib import Path
from Bio import SeqIO
from Bio.PDB import *
from Bio.PDB.Polypeptide import three_to_index, is_aa, index_to_one
from rdkit import Chem
import pandas as pd
import re

warnings.filterwarnings("ignore")

class ProteinParser:
    """Handles conversion of various protein input formats to sequences."""
    
    @staticmethod
    def from_fasta(filepath: str) -> List[str]:
        """Extract sequences from FASTA file."""
        return [str(record.seq) for record in SeqIO.parse(filepath, "fasta")]
    
    @staticmethod
    def from_pdb(filepath: str) -> List[str]:
        """Extract sequence from PDB structure."""
        parser = PDBParser(QUIET=True)
        structure = parser.get_structure('protein', filepath)
        
        sequence = ""
        for model in structure:
            for chain in model:
                for residue in chain:
                    if is_aa(residue.get_resname(), standard=True):
                        try:
                            sequence += index_to_one(three_to_index(residue.get_resname()))
                        except KeyError:
                            print(f"Warning: Unknown amino acid {residue.get_resname()}", file=sys.stderr)
        
        if not sequence:
            raise ValueError("No valid amino acid sequence found in structure")
        return [sequence]
    
    @staticmethod
    def from_sdf(filepath: str) -> List[str]:
        """Extract sequences from SDF file."""
        sequences = []
        supplier = Chem.SDMolSupplier(filepath)
        
        for mol in supplier:
            if mol is not None:
                sequence = None
                # Try property fields first
                for prop in mol.GetPropNames():
                    if 'SEQUENCE' in prop.upper():
                        sequence = mol.GetProp(prop)
                        break
                
                # Fall back to residue information
                if not sequence:
                    try:
                        residues = []
                        for atom in mol.GetAtoms():
                            info = atom.GetPDBResidueInfo()
                            if info and is_aa(info.GetResidueName(), standard=True):
                                residues.append(index_to_one(three_to_index(info.GetResidueName())))
                        sequence = ''.join(residues)
                    except:
                        continue
                
                if sequence:
                    # Clean sequence
                    sequence = re.sub(r'[^ACDEFGHIKLMNPQRSTVWY]', '', sequence.upper())
                    if sequence:
                        sequences.append(sequence)
        
        if not sequences:
            raise ValueError(f"No valid protein sequences found in file")
        return sequences
    
    @staticmethod
    def from_txt(filepath: str) -> List[str]:
        """Read sequences from text file."""
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]

class MoleculeParser:
    """Handles conversion of various molecule input formats to SMILES."""
    
    @staticmethod
    def from_sdf(filepath: str) -> List[str]:
        """Convert SDF molecules to canonical SMILES."""
        smiles_list = []
        supplier = Chem.SDMolSupplier(filepath)
        
        for mol in supplier:
            if mol is not None:
                smiles = Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)
                smiles_list.append(smiles)
        
        if not smiles_list:
            raise ValueError(f"No valid molecules found in file")
        return smiles_list
    
    @staticmethod
    def from_pdb(filepath: str) -> List[str]:
        """Convert PDB molecule to canonical SMILES."""
        mol = Chem.MolFromPDBFile(filepath)
        if mol is None:
            raise ValueError(f"Failed to parse PDB file")
        return [Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)]
    
    @staticmethod
    def from_cif(filepath: str) -> List[str]:
        """Convert CIF molecule to canonical SMILES."""
        mol = Chem.MolFromCIFFile(filepath)
        if mol is None:
            raise ValueError(f"Failed to parse CIF file")
        return [Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)]
    
    @staticmethod
    def from_txt(filepath: str) -> List[str]:
        """Read SMILES from text file."""
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]

def is_likely_file_path(input_str: str) -> bool:
    """Determine if the provided string is likely a file path.
    If the string contains newline characters or is longer than 200 characters, we assume it's direct input.
    Otherwise, check if it exists as a file using Path.is_file().
    """
    if "\n" in input_str or len(input_str) > 50:
        return False
    try:
        return Path(input_str).is_file()
    except OSError:
        return False

def parse_input(input_data: Union[str, List[str]], parser_class) -> List[str]:
    """Convert input data to list of sequences/SMILES using appropriate parser."""
    # Handle list input (e.g. from command line arguments)
    if isinstance(input_data, list):
        # If any item is a file path based on our heuristic, try to parse it
        if any(is_likely_file_path(item) for item in input_data):
            if len(input_data) > 1:
                raise ValueError("When using file input, please provide only one file")
            return parse_input(input_data[0], parser_class)
        # Otherwise treat as direct sequences/SMILES
        return input_data
    
    # Handle single string input
    if isinstance(input_data, str):
        # Check if it's likely a file path
        if is_likely_file_path(input_data):
            ext = Path(input_data).suffix.lower()
            parser_method = getattr(parser_class, f"from_{ext[1:]}", None)
            if parser_method:
                return parser_method(input_data)
            raise ValueError(f"Unsupported file extension: {ext}")
        # Otherwise treat as direct sequence/SMILES
        return [input_data]
    
    raise ValueError("Input must be a string or list of strings")

def format_results(predictions: List[Dict], proteins: List[str], molecules: List[str]) -> List[Dict]:
    """Format prediction results with input sequences."""
    return [{
        'protein': proteins[i],
        'molecule': molecules[i],
        'neg_log10_affinity_M': pred['neg_log10_affinity_M'],
        'affinity_uM': pred['affinity_uM']
    } for i, pred in enumerate(predictions)]

def write_results(results: List[Dict], output_path: str):
    """Write results to specified output format."""
    if output_path == 'stdout':
        for result in results:
            print(f"protein: {result['protein']}, molecule: {result['molecule']}, "
                  f"neg_log10_affinity_M: {result['neg_log10_affinity_M']:.4f}, "
                  f"affinity_uM: {result['affinity_uM']:.4f}")
        return

    ext = Path(output_path).suffix.lower()
    if ext == '.json':
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=4)
    elif ext == '.csv':
        df = pd.DataFrame(results)
        df.to_csv(output_path, index=False)
    else:
        with open(output_path, 'w') as f:
            for result in results:
                f.write(f"protein: {result['protein']}, molecule: {result['molecule']}, "
                       f"neg_log10_affinity_M: {result['neg_log10_affinity_M']:.4f}, "
                       f"affinity_uM: {result['affinity_uM']:.4f}\n")

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="PLAPT: Protein-Ligand Affinity Prediction Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-p', '--proteins', type=str, nargs='+', required=True,
                      help='Protein sequence(s) or path to file (fasta/pdb/sdf/txt)')
    parser.add_argument('-m', '--molecules', type=str, nargs='+', required=True,
                      help='SMILES string(s) or path to file (sdf/pdb/cif/txt)')
    parser.add_argument('-b', '--batch-size', type=int, default=4,
                      help='Batch size for predictions')
    parser.add_argument('-o', '--output', type=str, default='stdout',
                      help='Output file path (supports csv/json/txt)')
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    try:
        # 1. Parse inputs to canonical formats
        proteins = parse_input(args.proteins, ProteinParser)
        molecules = parse_input(args.molecules, MoleculeParser)
        
        # 2. Ensure input lengths match
        if len(proteins) == 1:
            proteins = proteins * len(molecules)
        elif len(molecules) == 1:
            molecules = molecules * len(proteins)
        elif len(proteins) != len(molecules):
            raise ValueError("Number of proteins and molecules must match or one must be singular")
        
        # 3. Run inference
        plapt = Plapt(use_tqdm=True)
        predictions = plapt.predict_affinity(proteins, molecules)
        
        # 4. Format results
        results = format_results(predictions, proteins, molecules)
        
        # 5. Output results
        write_results(results, args.output)
        
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

