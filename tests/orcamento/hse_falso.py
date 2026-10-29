"""HSE em memória para testar o processador sem navegador."""
from pathlib import Path

from orcamento.processador import Cliente, HseIndisponivel, Produto, SalvoIncerto

CLIENTE_VENTURA = Cliente("18373", "VENTURA COMERCIO VAREJISTA DE TECNOLOGIA LTDA", "12.345.678/0001-90")
MOUSE = Produto("13370", "DELL MOUSE OPTICO MS116", True)


class HseFalso:
    def __init__(self, clientes=None, vendedores=None, produtos=None, falhar_em=(), indisponivel_em=(),
                 marcas=("DELL", "MIDEA", "LG"), grupos=("INFORMATICA", "ELETRODOMÉSTICOS"), ncms=("84716053",)):
        self.lista_marcas = list(marcas)
        self.lista_grupos = list(grupos)
        self.ncms = set(ncms)
        self.clientes = list(clientes if clientes is not None else [CLIENTE_VENTURA])
        self.vendedores = set(vendedores if vendedores is not None else ["ELIZIANE AMORIM ROSA BARROS"])
        self.produtos = list(produtos if produtos is not None else [MOUSE])
        self.falhar_em = set(falhar_em)
        self.indisponivel_em = set(indisponivel_em)
        self.chamadas: list[tuple] = []
        self.rascunho: str | None = None
        self.avisos: list[str] = []
        self.avisos_ao_montar: list[str] = []  # o que o HSE "mostra" ao montar o orçamento
        self._prox_codigo = 90000

    def _registrar(self, nome, *args):
        self.chamadas.append((nome, *args))
        if nome in self.indisponivel_em:
            raise HseIndisponivel(f"{nome}: HSE fora do ar")
        if nome in self.falhar_em:
            raise RuntimeError(f"{nome}: falha simulada")

    def nomes(self) -> list[str]:
        return [c[0] for c in self.chamadas]

    def __enter__(self):
        self._registrar("login")
        return self

    def __exit__(self, *exc):
        return False

    def buscar_cliente(self, chave: str) -> list[Cliente]:
        self._registrar("buscar_cliente", chave)
        return [c for c in self.clientes if chave in (c.codigo, c.documento) or chave in c.nome]

    def vendedor_existe(self, nome: str) -> bool:
        self._registrar("vendedor_existe", nome)
        return nome in self.vendedores

    def buscar_produtos(self, termo: str) -> list[Produto]:
        self._registrar("buscar_produtos", termo)
        t = termo.upper()
        return [p for p in self.produtos if t in p.codigo or t in p.descricao.upper()]

    def marcas(self) -> list[str]:
        return self.lista_marcas

    def grupos(self) -> list[str]:
        return self.lista_grupos

    def ncm_existe(self, ncm: str) -> bool:
        self._registrar("ncm_existe", ncm)
        return ncm in self.ncms

    def cadastrar_produto(self, item, filial: int, salvar: bool) -> str | None:
        self._registrar("cadastrar_produto", item.descricao_cadastro, filial, salvar)
        if not salvar:
            return None
        self._prox_codigo += 1
        return str(self._prox_codigo)

    def montar_orcamento(self, orc, cliente, itens, incluir: bool) -> None:
        self.avisos = list(self.avisos_ao_montar)
        if incluir:
            self.rascunho = "77777"
        self._registrar("montar_orcamento", cliente.codigo, [(i.numero, p and p.codigo) for i, p in itens], incluir)

    def salvar_orcamento(self) -> str:
        if "salvo_incerto" in self.falhar_em:  # clicou Salvar, mas a confirmação falhou
            self.chamadas.append(("salvar_orcamento",))
            self.rascunho = None
            raise SalvoIncerto("55555", "timeout ao reabrir o pedido")
        self._registrar("salvar_orcamento")
        self.rascunho = None
        return "55555"

    def baixar_dav(self, numero: str, destino: Path) -> None:
        self._registrar("baixar_dav", numero, destino)
        destino.write_bytes(b"%PDF-1.4 falso")

    def cancelar_rascunho(self) -> str | None:
        self._registrar("cancelar_rascunho")
        n, self.rascunho = self.rascunho, None
        return n
