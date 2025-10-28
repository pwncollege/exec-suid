{
  description = "exec-suid Rust utility packaged with Nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      package = pkgs.pkgsStatic.rustPlatform.buildRustPackage {
        pname = "exec-suid";
        version = "0.1.6";
        src = ./.;
        cargoLock.lockFile = ./Cargo.lock;
        doCheck = true;
      };
    in
    {
      packages.${system}.default = package;
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = with pkgs; [
          cargo
          clippy
          rust-analyzer
          rustfmt
        ];
      };
    };
}
